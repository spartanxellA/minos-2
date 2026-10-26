"""Motor de riesgo: calcula el IRR de cada objetivo, guarda el punto de la serie, evalúa alertas y avisa al tablero."""
import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from .. import db
from ..bus import Bus
from ..config import RiskEngineSettings
from ..domain.mentions import Sentiment
from ..domain.risk import (
    LEVEL_LABEL, AlertKind, IndexWeights, VolumeBaseline, evaluate_alerts, media_risk, reputation_index,
)
from ..notifications import AlertNotice, Notifier
from ..schemas import AlertOut, RiskOut

log = logging.getLogger(__name__)


class _Scored:
    """Adapta una fila de mención a lo que espera el cálculo de riesgo (sentimiento como enum)."""

    __slots__ = ("_m", "sentiment")

    def __init__(self, m: db.Mention) -> None:
        self._m = m
        self.sentiment = Sentiment(m.sentiment)

    def __getattr__(self, name):
        return getattr(self._m, name)


# Condiciones que siguen activas en recálculos seguidos; las menciones graves son eventos únicos y no se agrupan.
LASTING_ALERTS = {AlertKind.INDEX_JUMP, AlertKind.NEGATIVE_SPIKE}


class RiskEngine:
    def __init__(self, database: db.Database, bus: Bus, settings: RiskEngineSettings, notifier: Notifier | None = None) -> None:
        self._db = database
        self._bus = bus
        self._s = settings
        self._notifier = notifier

    async def run(self) -> None:
        next_full = datetime.min.replace(tzinfo=UTC)
        while True:
            try:
                if datetime.now(UTC) >= next_full:
                    # Con varias réplicas, una sola hace el recálculo completo de cada periodo.
                    period = self._s.full_recompute_every.total_seconds()
                    if await self._bus.try_lock("risk-full", period * 0.9):
                        await self.recompute_all()
                    next_full = datetime.now(UTC) + self._s.full_recompute_every
                timeout = max((next_full - datetime.now(UTC)).total_seconds(), 0.05)
                for target_id in await self._bus.next_recompute(timeout):
                    await self.recompute(target_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Fallo en el motor de riesgo")
                await asyncio.sleep(5)

    async def recompute_all(self) -> None:
        async with self._db.session() as session:
            ids = (await session.scalars(select(db.Target.id).where(db.Target.enabled.is_(True)))).all()
        for target_id in ids:
            await self.recompute(target_id)

    async def recompute(self, target_id: uuid.UUID) -> db.RiskSnapshot:
        now = datetime.now(UTC)
        window_start = now - self._s.window
        M = db.Mention
        async with self._db.session() as session:
            window = (await session.scalars(
                select(M).where(M.target_id == target_id, M.published_at >= window_start)
            )).all()

            # Línea base: menciones por día en los días anteriores a la ventana.
            baseline_start = window_start - timedelta(days=self._s.baseline_days)
            history = (await session.scalars(
                select(M.published_at).where(
                    M.target_id == target_id, M.published_at >= baseline_start, M.published_at < window_start
                )
            )).all()
            buckets = [0] * self._s.baseline_days
            for published in history:
                day = int((window_start - published) / timedelta(days=1))
                if 0 <= day < self._s.baseline_days:
                    buckets[day] += 1
            first_seen = await session.scalar(select(func.min(M.published_at)).where(M.target_id == target_id))
            if first_seen is not None and first_seen.tzinfo is None:
                first_seen = first_seen.replace(tzinfo=UTC)
            history_days = 0 if first_seen is None else (window_start - first_seen) / timedelta(days=1)
            observed_days = int(min(max(history_days, 0), self._s.baseline_days))
            baseline = (
                VolumeBaseline.from_history(buckets[:observed_days]) if observed_days >= self._s.min_baseline_days else None
            )

            scored = [_Scored(m) for m in window]
            media = media_risk(scored, baseline)
            survey = await session.scalar(
                select(db.SurveyResponse.score)
                .where(db.SurveyResponse.target_id == target_id, db.SurveyResponse.score.is_not(None))
                .order_by(db.SurveyResponse.submitted_at.desc())
                .limit(1)
            )
            index = reputation_index(media.score, survey, IndexWeights(self._s.media_weight, self._s.survey_weight))

            snapshot = db.RiskSnapshot(
                target_id=target_id, at=now, index=index.score, level=index.level.value,
                media_score=round(media.score, 2), survey_score=survey,
                negativity=round(media.negativity, 4), severity=round(media.severity, 4),
                volume_anomaly=round(media.volume_anomaly, 4), mention_count=media.mention_count,
                positive=sum(1 for m in scored if m.sentiment == Sentiment.POSITIVE),
                negative=sum(1 for m in scored if m.sentiment == Sentiment.NEGATIVE),
                neutral=sum(1 for m in scored if m.sentiment == Sentiment.NEUTRAL),
                top_drivers=[str(d) for d in media.top_drivers],
            )

            R = db.RiskSnapshot
            day_ago = await session.scalar(
                select(R.index).where(R.target_id == target_id, R.at <= now - timedelta(hours=24)).order_by(R.at.desc()).limit(1)
            )
            last_run = await session.scalar(select(func.max(R.at)).where(R.target_id == target_id))
            if last_run is not None and last_run.tzinfo is None:
                last_run = last_run.replace(tzinfo=UTC)
            new_mentions = [m for m in scored if last_run is None or m.ingested_at > last_run]

            alerts = evaluate_alerts(day_ago, index.score, media, new_mentions)
            if any(a.kind in LASTING_ALERTS for a in alerts):
                A = db.AlertRecord
                recent = set((await session.scalars(
                    select(A.kind).where(A.target_id == target_id, A.at >= now - self._s.alert_cooldown)
                )).all())
                alerts = [a for a in alerts if a.kind not in LASTING_ALERTS or a.kind.value not in recent]
            session.add(snapshot)
            session.add_all(
                db.AlertRecord(target_id=target_id, at=now, kind=a.kind.value, title=a.title, message=a.message,
                               mention_id=a.mention_id)
                for a in alerts
            )
            await session.commit()

            target_name = await session.scalar(select(db.Target.name).where(db.Target.id == target_id)) or str(target_id)

        await self._bus.publish(target_id, "riskUpdated", RiskOut.of(snapshot))
        for a in alerts:
            await self._bus.publish(target_id, "alertRaised", AlertOut.of_alert(a).model_copy(update={"at": now}))
        if alerts and self._notifier is not None:
            urls = {m.id: m.url for m in scored}
            self._notifier.dispatch([
                AlertNotice(
                    target_id=target_id, target_name=target_name, at=now, kind=a.kind.value, title=a.title,
                    message=a.message, index=index.score, level_label=LEVEL_LABEL[index.level],
                    dashboard_url=self._notifier.dashboard_link(target_id), mention_url=urls.get(a.mention_id),
                )
                for a in alerts
            ])
        return snapshot
