"""Descarga de las listas oficiales y carga de las propias.

Cada lista se descarga según su frecuencia (OFAC cada 6 h, las demás cada día). Si el archivo no cambió (misma
huella SHA-256) no se procesa. Si cambió, se agregan los registros nuevos, se actualizan los modificados y se borran
los que salieron; el revisor de objetivos lo nota porque cambia la versión de la lista.
"""
import asyncio
import hashlib
import itertools
import json
import logging
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime

import httpx
from sqlalchemy import delete, insert, select, update

from .. import db
from ..bus import Bus
from ..config import WatchlistSettings
from ..connectors.base import redact_secrets
from ..domain.screening import WatchlistRecord
from .sources import OFFICIAL_SOURCES, OfficialSource

log = logging.getLogger(__name__)

TICK_SECONDS = 60
BATCH = 2000


def record_fingerprint(r: WatchlistRecord) -> str:
    payload = [r.kind.value, r.name, list(r.aliases), list(r.birth_dates), list(r.nationalities), list(r.identifiers),
               list(r.programs), r.listed_on, r.status, r.url, r.notes]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def _entry_row(slug: str, ext: str, r: WatchlistRecord) -> dict:
    return {
        "source": slug, "external_id": ext, "kind": r.kind.value, "name": r.name[:500],
        "aliases": [a[:500] for a in r.aliases], "birth_dates": list(r.birth_dates),
        "nationalities": list(r.nationalities), "identifiers": list(r.identifiers), "programs": list(r.programs),
        "listed_on": (r.listed_on or None) and r.listed_on[:32], "status": (r.status or None) and r.status[:64],
        "url": r.url, "notes": r.notes, "fingerprint": record_fingerprint(r),
    }


async def batches(records: Iterable[WatchlistRecord], size: int = BATCH) -> AsyncIterator[list[WatchlistRecord]]:
    """Lee los registros por tandas en otro hilo: una lista de cientos de miles no se carga completa en memoria ni
    detiene al servidor mientras se lee."""
    it = iter(records)
    while batch := await asyncio.to_thread(lambda: list(itertools.islice(it, size))):
        yield batch


async def store_entries(session, slug: str, records: Iterable[WatchlistRecord] | AsyncIterator[list[WatchlistRecord]]
                        ) -> tuple[int, int, int, int]:
    """Deja en la base exactamente los registros recibidos. Devuelve (total, nuevos, modificados, borrados)."""
    E = db.WatchlistEntry
    existing = {ext: (id_, fp) for id_, ext, fp in (await session.execute(
        select(E.id, E.external_id, E.fingerprint).where(E.source == slug)
    )).all()}
    seen: set[str] = set()
    new = changed = 0
    chunks = records if hasattr(records, "__aiter__") else batches(records)
    async for chunk in chunks:
        inserts = []
        for r in chunk:
            ext = r.external_id[:200]
            if ext in seen:
                continue
            seen.add(ext)
            row = _entry_row(slug, ext, r)
            if ext not in existing:
                inserts.append(row)
            elif existing[ext][1] != row["fingerprint"]:
                changed += 1
                await session.execute(update(E).where(E.id == existing[ext][0]).values(**row))
        if inserts:
            new += len(inserts)
            await session.execute(insert(E), inserts)
    gone = [id_ for ext, (id_, _) in existing.items() if ext not in seen]
    for i in range(0, len(gone), BATCH):
        await session.execute(delete(E).where(E.id.in_(gone[i:i + BATCH])))
    return len(seen), new, changed, len(gone)


async def save_list(database: db.Database, slug: str,
                    records: Iterable[WatchlistRecord] | AsyncIterator[list[WatchlistRecord]], version: str,
                    now: datetime, *, official: OfficialSource | None = None, name: str | None = None,
                    category: str | None = None, uploaded_by: str | None = None) -> tuple[int, int, int, int]:
    async with database.session() as session:
        row = await session.get(db.WatchlistSource, slug)
        if row is None:
            row = db.WatchlistSource(slug=slug, name=name or slug, category=category or "other",
                                     custom=official is None, entry_count=0)
            session.add(row)
        if official is not None:
            row.name, row.category = official.name, official.category
        else:
            row.name, row.category, row.uploaded_by = name or row.name, category or row.category, uploaded_by
        await session.flush()
        counts = await store_entries(session, slug, records)
        row.version, row.entry_count = version, counts[0]
        row.last_checked_at, row.last_changed_at, row.last_error = now, now, None
        await session.commit()
    log.info("Lista %s: %d registros (%d nuevos, %d cambiados, %d retirados)", slug, *counts)
    return counts


class WatchlistSync:
    def __init__(self, database: db.Database, bus: Bus, http: httpx.AsyncClient, settings: WatchlistSettings) -> None:
        self._db = database
        self._bus = bus
        self._http = http
        self._s = settings

    @property
    def sources(self) -> list[OfficialSource]:
        return [OFFICIAL_SOURCES[s] for s in self._s.sources if s in OFFICIAL_SOURCES and self.is_configured(s)]

    def is_configured(self, slug: str) -> bool:
        return slug != "worldbank" or bool(self._s.worldbank_api_key)

    async def run(self) -> None:
        while True:
            try:
                for source in self.sources:
                    if await self._due(source) and await self._bus.try_lock(f"watchlist:{source.slug}", 30 * 60):
                        try:
                            await self.refresh(source)
                        finally:
                            await self._bus.release(f"watchlist:{source.slug}")
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Fallo al actualizar las listas negras")
            await asyncio.sleep(TICK_SECONDS)

    async def _due(self, source: OfficialSource) -> bool:
        async with self._db.session() as session:
            row = await session.get(db.WatchlistSource, source.slug)
        if row is None or row.last_checked_at is None:
            return True
        wait = self._s.retry_after if row.last_error else source.refresh_every
        return datetime.now(UTC) - row.last_checked_at >= wait

    async def download(self, source: OfficialSource) -> bytes:
        url = self._s.urls.get(source.slug, source.url)
        headers = {k: v.format(worldbank_api_key=self._s.worldbank_api_key) for k, v in source.headers}
        response = await self._http.get(url, headers=headers, follow_redirects=True,
                                        timeout=self._s.download_timeout.total_seconds())
        response.raise_for_status()
        return response.content

    async def refresh(self, source: OfficialSource) -> None:
        """Descarga y guarda una lista. Un error queda en la lista (panel de listas) y no tumba al worker."""
        now = datetime.now(UTC)
        try:
            data = await self.download(source)
            version = hashlib.sha256(data).hexdigest()
            async with self._db.session() as session:
                row = await self._row(session, source)
                if row.version == version and row.entry_count:
                    row.last_checked_at, row.last_error = now, None
                    await session.commit()
                    return
            records = await asyncio.to_thread(lambda: list(source.parser(data, source.slug)))
            if not records:
                raise ValueError("La lista llegó vacía; se conserva la versión anterior.")
            await save_list(self._db, source.slug, records, version, now, official=source)
        except asyncio.CancelledError:
            raise
        except Exception as ex:
            message = redact_secrets(f"{type(ex).__name__}: {ex}")[:500]
            log.warning("No se pudo actualizar la lista %s: %s", source.slug, message)
            async with self._db.session() as session:
                row = await self._row(session, source)
                row.last_checked_at, row.last_error = now, message
                await session.commit()

    async def _row(self, session, source: OfficialSource) -> db.WatchlistSource:
        row = await session.get(db.WatchlistSource, source.slug)
        if row is None:
            row = db.WatchlistSource(slug=source.slug, name=source.name, category=source.category, custom=False,
                                     entry_count=0)
            session.add(row)
        return row
