"""Revisión de los objetivos contra todas las listas cargadas.

Cada vuelta calcula una llave por objetivo con sus datos (nombre, alias, fecha de nacimiento, nacionalidad,
documentos) y la versión de las listas. Si la llave cambió desde la última revisión, se vuelve a revisar: así un
objetivo nuevo o editado se revisa en segundos, y todos se revisan otra vez cuando alguna lista cambia.
"""
import asyncio
import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select

from .. import db
from ..bus import Bus
from ..config import WatchlistSettings
from ..domain.risk import LEVEL_LABEL, RiskLevel
from ..domain.screening import MatchResult, ScreeningIndex, Subject
from ..domain.targets import TargetKind
from ..notifications import AlertNotice, Notifier
from ..schemas import AlertOut
from .schemas import MatchOut, ScreeningOut
from .sync import record_fingerprint

log = logging.getLogger(__name__)

ALERT_KIND = "WatchlistMatch"


def subject_of(target: db.Target) -> Subject:
    return Subject(
        kind=TargetKind(target.kind), names=target.to_domain().search_names(), birth_date=target.birth_date,
        nationality=target.nationality, identifiers=sorted((target.identifiers or {}).values()),
    )


def screening_key(lists_version: str, s: Subject) -> str:
    payload = [lists_version, s.kind.value, list(s.names), s.birth_date, s.nationality, list(s.identifiers)]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def entry_snapshot(m: MatchResult) -> dict:
    r = m.record
    return {
        "kind": r.kind.value, "name": r.name, "aliases": list(r.aliases)[:30], "birthDates": list(r.birth_dates),
        "nationalities": list(r.nationalities), "identifiers": list(r.identifiers), "programs": list(r.programs),
        "listedOn": r.listed_on, "status": r.status, "url": r.url, "notes": (r.notes or "")[:1000] or None,
    }


async def screening_summary(session, target_id: uuid.UUID, include_dismissed: bool = True) -> ScreeningOut:
    S = db.ScreeningMatch
    rows = (await session.scalars(select(S).where(S.target_id == target_id).order_by(S.score.desc()))).all()
    # Se muestran las vigentes y, como historia, las confirmadas que salieron de la lista.
    shown = [m for m in rows if (m.active or m.status == "confirmed") and (include_dismissed or m.status != "dismissed")]
    state = await session.get(db.ScreeningState, target_id)
    lists = await session.scalar(select(func.count()).select_from(db.WatchlistSource).where(db.WatchlistSource.entry_count > 0))
    pending = sum(1 for m in rows if m.active and m.status == "pending")
    confirmed = sum(1 for m in rows if m.active and m.status == "confirmed")
    status = "not_screened" if state is None else "confirmed" if confirmed else "possible" if pending else "clear"
    return ScreeningOut(
        target_id=target_id, status=status, screened_at=state.screened_at if state else None, pending=pending,
        confirmed=confirmed, matches=[MatchOut.of(m) for m in shown], lists=lists or 0,
    )


class Screener:
    def __init__(self, database: db.Database, bus: Bus, settings: WatchlistSettings, notifier: Notifier | None = None,
                 risk_engine=None) -> None:
        self._db = database
        self._bus = bus
        self._s = settings
        self._notifier = notifier
        self._engine = risk_engine
        self._index: ScreeningIndex | None = None
        self._index_version: str | None = None

    async def run(self) -> None:
        every = self._s.screen_every.total_seconds()
        while True:
            try:
                if await self._bus.try_lock("screening", max(every * 4, 120)):
                    try:
                        await self.cycle()
                    finally:
                        await self._bus.release("screening")
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Fallo en la revisión de listas negras")
            await asyncio.sleep(every)

    async def lists_version(self) -> str | None:
        async with self._db.session() as session:
            rows = (await session.execute(
                select(db.WatchlistSource.slug, db.WatchlistSource.version)
                .where(db.WatchlistSource.entry_count > 0).order_by(db.WatchlistSource.slug)
            )).all()
        return hashlib.sha256(json.dumps([list(r) for r in rows]).encode()).hexdigest() if rows else None

    async def index(self, version: str) -> ScreeningIndex:
        if self._index is None or self._index_version != version:
            async with self._db.session() as session:
                entries = (await session.scalars(select(db.WatchlistEntry))).all()
                records = [e.to_record() for e in entries]
            self._index = await asyncio.to_thread(ScreeningIndex, records)
            self._index_version = version
            log.info("Índice de listas negras: %d registros", len(self._index))
        return self._index

    async def cycle(self) -> int:
        """Revisa los objetivos pendientes. Devuelve cuántos revisó."""
        version = await self.lists_version()
        if version is None:
            return 0
        async with self._db.session() as session:
            targets = (await session.scalars(select(db.Target).where(db.Target.enabled.is_(True)))).all()
            states = dict((await session.execute(select(db.ScreeningState.target_id, db.ScreeningState.key))).all())
        done = 0
        for target in targets:
            subject = subject_of(target)
            key = screening_key(version, subject)
            if states.get(target.id) == key:
                continue
            index = await self.index(version)
            await self.apply(target, index.screen(subject), key)
            done += 1
        return done

    async def apply(self, target: db.Target, results: list[MatchResult], key: str) -> None:
        now = datetime.now(UTC)
        S = db.ScreeningMatch
        raised: list[db.ScreeningMatch] = []
        confirmed_changed = False
        async with self._db.session() as session:
            sources = {s.slug: s for s in (await session.scalars(select(db.WatchlistSource))).all()}
            existing = {(m.source, m.external_id): m for m in (await session.scalars(
                select(S).where(S.target_id == target.id))).all()}
            for res in results:
                src = sources.get(res.record.source)
                fp = record_fingerprint(res.record)
                m = existing.pop((res.record.source, res.record.external_id), None)
                if m is None:
                    m = S(target_id=target.id, source=res.record.source, external_id=res.record.external_id,
                          status="pending", first_seen_at=now)
                    session.add(m)
                    raised.append(m)
                elif m.status == "dismissed" and m.entry_fingerprint != fp:
                    # El registro de la lista cambió desde que se descartó: se vuelve a revisar.
                    m.status = "pending"
                    m.review_note = f"Reabierta: el registro cambió en la lista. Nota anterior: {m.review_note or '—'}"
                    raised.append(m)
                elif not m.active and m.status != "dismissed":
                    confirmed_changed |= m.status == "confirmed"
                    if m.status == "pending":
                        raised.append(m)
                m.category = src.category if src else "other"
                m.source_name = src.name if src else res.record.source
                m.listed_name, m.matched_name = res.listed_name[:500], res.matched_name[:500]
                m.score, m.strength, m.reasons = res.score, res.strength.value, res.reasons
                m.entry, m.entry_fingerprint = entry_snapshot(res), fp
                m.active, m.last_seen_at = True, now
            for m in existing.values():
                if m.active:
                    m.active = False
                    confirmed_changed |= m.status == "confirmed"
            state = await session.get(db.ScreeningState, target.id)
            if state is None:
                session.add(db.ScreeningState(target_id=target.id, key=key, screened_at=now))
            else:
                state.key, state.screened_at = key, now
            alerts = [
                db.AlertRecord(target_id=target.id, at=now, kind=ALERT_KIND, title="Posible coincidencia en lista negra",
                               message=f"«{m.listed_name}» en {m.source_name} ({m.score:.0f}% de parecido). "
                                       "Un analista debe confirmarla o descartarla.")
                for m in raised
            ]
            session.add_all(alerts)
            await session.commit()
            summary = await screening_summary(session, target.id)
            latest = await session.scalar(select(db.RiskSnapshot).where(db.RiskSnapshot.target_id == target.id)
                                          .order_by(db.RiskSnapshot.at.desc()).limit(1))

        await self._bus.publish(target.id, "screeningUpdated", summary)
        for a in alerts:
            await self._bus.publish(target.id, "alertRaised", AlertOut.model_validate(a))
        if alerts and self._notifier is not None:
            self._notifier.dispatch([
                AlertNotice(
                    target_id=target.id, target_name=target.name, at=now, kind=ALERT_KIND, title=a.title,
                    message=a.message, index=latest.index if latest else 0,
                    level_label=LEVEL_LABEL[RiskLevel(latest.level)] if latest else "Sin cálculo",
                    dashboard_url=self._notifier.dashboard_link(target.id),
                )
                for a in alerts
            ])
        if confirmed_changed and self._engine is not None:
            await self._engine.recompute(target.id)
