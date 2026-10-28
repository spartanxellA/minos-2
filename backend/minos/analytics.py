"""Análisis general: qué sujetos se mencionan más, por tipo, y cómo cambian menciones e índice de riesgo por mes o año.

A diferencia del resto de la API, aquí no se mira un solo objetivo sino todos los monitoreados a la vez.
"""
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import db
from .auth import current_user
from .domain.mentions import Sentiment
from .domain.targets import TargetKind
from .schemas import Camel

Granularity = Literal["month", "year"]
PeriodParam = Annotated[str | None, Query(pattern=r"^\d{4}(-(0[1-9]|1[0-2]))?$")]


class SubjectTotal(Camel):
    target_id: uuid.UUID
    name: str
    kind: TargetKind
    enabled: bool
    mentions: int
    positive: int
    neutral: int
    negative: int
    severe: int
    # Último índice de riesgo calculado (sin importar el rango), para leerlo junto al volumen.
    last_index: float | None


class KindTotal(Camel):
    kind: TargetKind
    targets: int
    mentions: int
    negative: int


class KindPeriodCount(Camel):
    period: str
    kind: TargetKind
    count: int


class TargetPeriodCount(Camel):
    period: str
    target_id: uuid.UUID
    count: int


class TargetPeriodRisk(Camel):
    period: str
    target_id: uuid.UUID
    avg: float
    max: float


class KindPeriodRisk(Camel):
    period: str
    kind: TargetKind
    avg: float


class MentionsOverview(Camel):
    granularity: Granularity
    timezone: str
    # Todos los periodos del rango, con o sin datos, para que las gráficas no se salten meses vacíos.
    periods: list[str]
    ranking: list[SubjectTotal]
    by_kind: list[KindTotal]
    mentions_by_kind: list[KindPeriodCount]
    # Solo para los primeros `top` sujetos del ranking.
    mentions_by_target: list[TargetPeriodCount]
    risk_by_target: list[TargetPeriodRisk]
    # Promedio de los índices mensuales (o anuales) de cada sujeto del tipo, no de cada cálculo suelto.
    risk_by_kind: list[KindPeriodRisk]


async def get_session(request: Request):
    async with request.app.state.db.session() as session:
        yield session


analytics_router = APIRouter(prefix="/api/analytics", dependencies=[Depends(current_user)])


def _parse(value: str) -> tuple[int, int]:
    year, _, month = value.partition("-")
    return int(year), int(month or 1)


def _shift(year: int, month: int, months: int) -> tuple[int, int]:
    n = year * 12 + month - 1 + months
    return n // 12, n % 12 + 1


def _label(year: int, month: int, granularity: Granularity) -> str:
    return f"{year:04d}" if granularity == "year" else f"{year:04d}-{month:02d}"


def _periods(start: tuple[int, int], end: tuple[int, int], granularity: Granularity) -> list[str]:
    step = 12 if granularity == "year" else 1
    out, cur = [], start
    while cur <= end:
        out.append(_label(*cur, granularity))
        cur = _shift(*cur, step)
    return out


def _period_expr(column, granularity: Granularity, dialect: str, tz: str):
    if dialect == "postgresql":
        return func.to_char(func.timezone(tz, column), "YYYY" if granularity == "year" else "YYYY-MM")
    return func.strftime("%Y" if granularity == "year" else "%Y-%m", column)


@analytics_router.get("/mentions", response_model=MentionsOverview)
async def mentions_overview(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    granularity: Granularity = "month",
    since: PeriodParam = None,
    until: PeriodParam = None,
    kind: TargetKind | None = None,
    source: str | None = None,
    top: Annotated[int, Query(ge=1, le=50)] = 10,
    include_inactive: Annotated[bool, Query(alias="includeInactive")] = False,
):
    """Ranking de sujetos por menciones y series por mes o año. Por omisión: últimos 12 meses, o todos los años."""
    dialect = request.app.state.db.engine.dialect.name
    # SQLite (pruebas y tablero local) no tiene zonas horarias: ahí todo va en UTC.
    tz = request.app.state.settings.timezone if dialect == "postgresql" else "UTC"
    zone = ZoneInfo(tz)
    M, R, T = db.Mention, db.RiskSnapshot, db.Target

    now = datetime.now(zone)
    year_mode = granularity == "year"
    end = _parse(until) if until else (now.year, now.month)
    if year_mode:
        end = (end[0], 1)
    if since:
        start = _parse(since)
    elif year_mode:
        first = await session.scalar(select(func.min(M.published_at)))
        start = (first.astimezone(zone).year if first else end[0], 1)
    else:
        start = _shift(*end, -11)
    if year_mode:
        start = (start[0], 1)
    if start > end:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El inicio del rango es posterior al final.")
    periods = _periods(start, end, granularity)
    if len(periods) > 240:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El rango es demasiado largo; usa la vista por año.")
    lower = datetime(*start, 1, tzinfo=zone).astimezone(UTC)
    upper = datetime(*_shift(*end, 12 if year_mode else 1), 1, tzinfo=zone).astimezone(UTC)

    target_filter = []
    if kind:
        target_filter.append(T.kind == kind.value)
    if not include_inactive:
        target_filter.append(T.enabled.is_(True))
    targets = (await session.scalars(select(T).where(*target_filter).order_by(T.name))).all()
    by_id = {t.id: t for t in targets}

    mention_scope = [M.published_at >= lower, M.published_at < upper, *target_filter]
    if source:
        mention_scope.append(M.source == source)

    def count_if(condition):
        return func.sum(case((condition, 1), else_=0))

    totals = {
        target_id: (n, pos or 0, neu or 0, neg or 0, sev or 0)
        for target_id, n, pos, neu, neg, sev in await session.execute(
            select(
                M.target_id, func.count(), count_if(M.sentiment == Sentiment.POSITIVE.value),
                count_if(M.sentiment == Sentiment.NEUTRAL.value), count_if(M.sentiment == Sentiment.NEGATIVE.value),
                count_if(M.is_severe_accusation.is_(True)),
            ).join(T, T.id == M.target_id).where(*mention_scope).group_by(M.target_id)
        )
    }

    latest_at = select(R.target_id, func.max(R.at).label("at")).group_by(R.target_id).subquery()
    last_index = dict((await session.execute(
        select(R.target_id, R.index).join(latest_at, (R.target_id == latest_at.c.target_id) & (R.at == latest_at.c.at))
    )).all())

    ranking = sorted(
        (
            SubjectTotal(
                target_id=t.id, name=t.name, kind=TargetKind(t.kind), enabled=t.enabled,
                mentions=n, positive=pos, neutral=neu, negative=neg, severe=sev, last_index=last_index.get(t.id),
            )
            for t in targets
            for n, pos, neu, neg, sev in [totals.get(t.id, (0, 0, 0, 0, 0))]
        ),
        key=lambda s: (-s.mentions, -s.negative, s.name.lower()),
    )
    top_ids = [s.target_id for s in ranking[:top] if s.mentions > 0]

    by_kind = []
    for k in [kind] if kind else TargetKind:
        members = [s for s in ranking if s.kind == k]
        by_kind.append(KindTotal(
            kind=k, targets=len(members), mentions=sum(s.mentions for s in members),
            negative=sum(s.negative for s in members),
        ))

    m_period = _period_expr(M.published_at, granularity, dialect, tz)
    mentions_by_kind = [
        KindPeriodCount(period=p, kind=TargetKind(k), count=n)
        for p, k, n in await session.execute(
            select(m_period, T.kind, func.count()).join(T, T.id == M.target_id).where(*mention_scope)
            .group_by(m_period, T.kind)
        )
    ]
    mentions_by_target = [] if not top_ids else [
        TargetPeriodCount(period=p, target_id=t, count=n)
        for p, t, n in await session.execute(
            select(m_period, M.target_id, func.count()).join(T, T.id == M.target_id)
            .where(*mention_scope, M.target_id.in_(top_ids)).group_by(m_period, M.target_id)
        )
    ]

    r_period = _period_expr(R.at, granularity, dialect, tz)
    risk_rows = [] if not by_id else (await session.execute(
        select(r_period, R.target_id, func.avg(R.index), func.max(R.index))
        .where(R.at >= lower, R.at < upper, R.target_id.in_(list(by_id))).group_by(r_period, R.target_id)
    )).all()
    top_set = set(top_ids)
    risk_by_target = [
        TargetPeriodRisk(period=p, target_id=t, avg=round(avg, 2), max=round(mx, 2))
        for p, t, avg, mx in risk_rows if t in top_set
    ]
    kind_sums: dict[tuple[str, str], list[float]] = {}
    for p, t, avg, _ in risk_rows:
        kind_sums.setdefault((p, by_id[t].kind), []).append(avg)
    risk_by_kind = [
        KindPeriodRisk(period=p, kind=TargetKind(k), avg=round(sum(v) / len(v), 2))
        for (p, k), v in sorted(kind_sums.items())
    ]

    return MentionsOverview(
        granularity=granularity, timezone=tz, periods=periods,
        ranking=ranking, by_kind=by_kind, mentions_by_kind=mentions_by_kind, mentions_by_target=mentions_by_target,
        risk_by_target=risk_by_target, risk_by_kind=risk_by_kind,
    )
