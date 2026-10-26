"""Ingesta: recorre objetivo × conector cuando toca, filtra homónimos, deduplica, analiza una vez y guarda."""
import asyncio
import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from sqlalchemy import select

from .. import db
from ..analysis import MentionAnalyzer
from ..config import IngestionSettings
from ..connectors import ConnectorCursor, MentionConnector
from ..domain.mentions import MentionDraft, fingerprint
from ..domain.targets import MonitoredTarget, is_relevant
from ..realtime import RiskHub
from ..schemas import MentionOut

log = logging.getLogger(__name__)


class IngestionWorker:
    def __init__(
        self,
        database: db.Database,
        connectors: Sequence[MentionConnector],
        analyzer: MentionAnalyzer,
        hub: RiskHub,
        settings: IngestionSettings,
        on_new_mentions: Callable[[object], None],
    ) -> None:
        self._db = database
        self._connectors = connectors
        self._analyzer = analyzer
        self._hub = hub
        self._settings = settings
        self._on_new_mentions = on_new_mentions

    async def run(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Fallo en la ronda de ingesta")
            await asyncio.sleep(self._settings.tick.total_seconds())

    async def run_once(self) -> None:
        connectors = [c for c in self._connectors if c.is_configured]
        async with self._db.session() as session:
            targets = (await session.scalars(select(db.Target).where(db.Target.enabled.is_(True)))).all()

        for target_row in targets:
            target = target_row.to_domain()
            for connector in connectors:
                async with self._db.session() as session:
                    state = await session.get(db.ConnectorState, (target.id, connector.source))
                    if state is None:
                        state = db.ConnectorState(target_id=target.id, source=connector.source)
                        session.add(state)
                    now = datetime.now(UTC)
                    if state.last_run_at and now - state.last_run_at < connector.poll_interval:
                        continue
                    cursor = ConnectorCursor(state.value)
                    added: list[db.Mention] = []
                    error: str | None = None
                    try:
                        added = await self._ingest(session, connector, target, cursor)
                        state.value = cursor.value
                        state.last_error = None
                        state.last_run_at = datetime.now(UTC)
                        await session.commit()
                    except asyncio.CancelledError:
                        raise
                    except Exception as ex:
                        error = str(ex)[:2000] or type(ex).__name__
                        log.warning("El conector %s falló para %s: %s", connector.source, target.name, ex)

                if error is not None:
                    # Se descarta el lote incompleto y solo se registra el error; el cursor no avanza.
                    added = []
                    async with self._db.session() as session:
                        state = await session.get(db.ConnectorState, (target.id, connector.source))
                        if state is None:
                            state = db.ConnectorState(target_id=target.id, source=connector.source)
                            session.add(state)
                        state.last_error = error
                        state.last_run_at = datetime.now(UTC)
                        await session.commit()
                    continue

                log.info("%s → %s: %s menciones nuevas", connector.source, target.name, len(added))
                if added:
                    self._on_new_mentions(target.id)
                    latest = sorted(added, key=lambda m: m.published_at, reverse=True)[:20]
                    await self._hub.publish(target.id, "mentionsAdded", [MentionOut.of(m) for m in latest])

    async def _ingest(self, session, connector: MentionConnector, target: MonitoredTarget, cursor: ConnectorCursor) -> list[db.Mention]:
        drafts: list[MentionDraft] = []
        async for draft in connector.fetch(target, cursor):
            if is_relevant(target, draft.text):
                drafts.append(draft)
            if len(drafts) >= self._settings.max_mentions_per_run:
                break
        if not drafts:
            return []

        # Deduplicación por id externo y por huella del texto (retuits, notas replicadas).
        ids = [d.external_id for d in drafts]
        known_ids = set((await session.scalars(
            select(db.Mention.external_id).where(
                db.Mention.target_id == target.id, db.Mention.source == connector.source, db.Mention.external_id.in_(ids)
            )
        )).all())
        prints = [fingerprint(d.text) for d in drafts]
        since = datetime.now(UTC) - self._settings.duplicate_window
        known_prints = set((await session.scalars(
            select(db.Mention.fingerprint).where(
                db.Mention.target_id == target.id, db.Mention.published_at >= since, db.Mention.fingerprint.in_(prints)
            )
        )).all())

        fresh = []
        for d, fp in zip(drafts, prints):
            if d.external_id in known_ids or fp in known_prints:
                continue
            known_ids.add(d.external_id)
            known_prints.add(fp)
            fresh.append(d)
        if not fresh:
            return []

        analyses = await self._analyzer.analyze(fresh, target.name)
        mentions = [db.Mention.create(target.id, d, a) for d, a in zip(fresh, analyses)]
        session.add_all(mentions)
        await session.flush()
        return mentions
