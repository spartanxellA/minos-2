"""Ingesta en tiempo real de Bluesky (Jetstream).

Una sola réplica de workers mantiene la conexión (candado renovado en Redis); si muere, otra la toma al vencer.
Cada publicación se revisa contra todos los objetivos activos, y lo que coincide se guarda en lotes cortos con la
misma deduplicación y análisis que el resto de las fuentes."""
import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict

import httpx
import websockets
from sqlalchemy import select

from .. import db
from ..bus import Bus
from ..config import JetstreamSettings
from ..connectors.jetstream import ProfileDirectory, StreamPost, parse_event, subscribe_url
from ..domain.targets import MonitoredTarget, is_relevant_normalized, normalize
from .ingestion import IngestionWorker

log = logging.getLogger(__name__)

LOCK = "stream:jetstream"
LOCK_TTL = 60.0
TARGETS_REFRESH = 60.0


class LostLock(Exception):
    pass


class JetstreamIngestion:
    def __init__(self, database: db.Database, ingestion: IngestionWorker, bus: Bus, http: httpx.AsyncClient,
                 settings: JetstreamSettings) -> None:
        self._db = database
        self._ingestion = ingestion
        self._bus = bus
        self._settings = settings
        self._profiles = ProfileDirectory(http, settings)
        self._targets: list[MonitoredTarget] = []
        self._pending: dict[uuid.UUID, list[StreamPost]] = defaultdict(list)
        self._cursor_us: int | None = None

    async def run(self) -> None:
        while True:
            if not await self._bus.try_lock(LOCK, LOCK_TTL):
                await asyncio.sleep(LOCK_TTL / 3)
                continue
            log.info("Jetstream: esta réplica recibe Bluesky en vivo")
            try:
                await self._load_targets()  # antes de conectar, para no descartar lo primero que llegue
                async with asyncio.TaskGroup() as group:
                    group.create_task(self._keep_lock())
                    group.create_task(self._refresh_targets())
                    group.create_task(self._flush_loop())
                    group.create_task(self._consume())
            except* LostLock:
                log.warning("Jetstream: se perdió el candado; otra réplica sigue")
            except* Exception as group_error:
                log.error("Jetstream se detuvo; reintento en 5 s", exc_info=group_error)
                await asyncio.sleep(5)
            finally:
                await self.flush()
                await self._bus.release(LOCK)

    async def _keep_lock(self) -> None:
        while True:
            await asyncio.sleep(LOCK_TTL / 3)
            if not await self._bus.renew(LOCK, LOCK_TTL):
                raise LostLock()

    async def _load_targets(self) -> None:
        async with self._db.session() as session:
            rows = (await session.scalars(select(db.Target).where(db.Target.enabled.is_(True)))).all()
        self._targets = [r.to_domain() for r in rows]

    async def _refresh_targets(self) -> None:
        while True:
            await asyncio.sleep(TARGETS_REFRESH)
            await self._load_targets()

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(self._settings.flush_every.total_seconds())
            await self.flush()

    async def _consume(self) -> None:
        backoff = 1
        while True:
            if self._cursor_us is None:
                self._cursor_us = int((time.time() - self._settings.replay.total_seconds()) * 1_000_000)
            try:
                async with websockets.connect(subscribe_url(self._settings, self._cursor_us), max_size=2**22) as ws:
                    backoff = 1
                    async for raw in ws:
                        self.handle(json.loads(raw))
            except (OSError, websockets.WebSocketException) as ex:
                log.warning("Jetstream desconectado (%s); reconecto en %s s", ex, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    def handle(self, event: dict) -> None:
        """Avanza el cursor y aparta la publicación para cada objetivo que menciona."""
        self._cursor_us = event.get("time_us", self._cursor_us)
        post = parse_event(event)
        if post is None or not self._targets:
            return
        haystack = normalize(post.text)
        for target in self._targets:
            if is_relevant_normalized(target, haystack):
                self._pending[target.id].append(post)

    def set_targets(self, targets: list[MonitoredTarget]) -> None:
        self._targets = targets

    async def flush(self) -> None:
        if not self._pending:
            return
        pending, self._pending = self._pending, defaultdict(list)
        targets = {t.id: t for t in self._targets}
        authors = await self._profiles.resolve({p.did for posts in pending.values() for p in posts})
        for target_id, posts in pending.items():
            target = targets.get(target_id)
            if target is None:
                continue
            drafts = [ProfileDirectory.draft(p, authors[p.did]) for p in posts]
            try:
                async with self._db.session() as session:
                    added = await self._ingestion.store(session, target, "bluesky", drafts)
                    await session.commit()
            except Exception:
                log.exception("Jetstream: no se pudieron guardar %s menciones de %s", len(drafts), target.name)
                continue
            if added:
                log.info("jetstream → %s: %s menciones nuevas", target.name, len(added))
            await self._ingestion.announce(target_id, added)
