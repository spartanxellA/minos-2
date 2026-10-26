"""Rutas REST bajo /api y el WebSocket del tablero."""
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect, status
from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import db
from .auth import Role, current_user, require_role, websocket_user
from .domain.mentions import Sentiment
from .schemas import (
    AlertOut, BreakdownOut, ChannelStatus, ConnectorStateOut, Influencer, MentionOut, RiskOut, SourceError,
    SourceSentimentCount, SourceStatus, SourcesOut, SurveyResponseOut, SurveySubmission, SurveySummary, TargetInput,
    TargetOut, TopicCount,
)
from .surveys import SurveyCatalog, SurveyDefinition


async def get_session(request: Request):
    async with request.app.state.db.session() as session:
        yield session


Session = Annotated[AsyncSession, Depends(get_session)]
router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])
Analyst = [Depends(require_role(Role.ANALYST))]
Admin = [Depends(require_role(Role.ADMIN))]


def _clean(values: list[str]) -> list[str]:
    seen, out = set(), []
    for v in values:
        v = v.strip()
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out


def _apply(target: db.Target, body: TargetInput) -> None:
    target.name = body.name.strip()
    target.kind = body.kind.value
    target.aliases = _clean(body.aliases)
    target.keywords = _clean(body.keywords)
    target.excluded_terms = _clean(body.excluded_terms)
    target.handles = {k.strip(): v.strip() for k, v in body.handles.items() if k.strip() and v.strip()}
    target.enabled = body.enabled


async def _target_or_404(session: AsyncSession, target_id: uuid.UUID) -> db.Target:
    target = await session.get(db.Target, target_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Objetivo no encontrado")
    return target


# --- Objetivos ------------------------------------------------------------------------------------


@router.get("/targets", response_model=list[TargetOut])
async def list_targets(session: Session):
    return (await session.scalars(select(db.Target).order_by(db.Target.name))).all()


@router.get("/targets/{target_id}", response_model=TargetOut)
async def get_target(target_id: uuid.UUID, session: Session):
    return await _target_or_404(session, target_id)


@router.post("/targets", response_model=TargetOut, status_code=status.HTTP_201_CREATED, dependencies=Analyst)
async def create_target(body: TargetInput, session: Session, response: Response):
    if not body.name.strip():
        raise HTTPException(422, "El nombre es obligatorio.")
    target = db.Target(id=uuid.uuid4(), created_at=datetime.now(UTC))
    _apply(target, body)
    session.add(target)
    await session.commit()
    response.headers["Location"] = f"/api/targets/{target.id}"
    return target


@router.put("/targets/{target_id}", response_model=TargetOut, dependencies=Analyst)
async def update_target(target_id: uuid.UUID, body: TargetInput, session: Session):
    target = await _target_or_404(session, target_id)
    _apply(target, body)
    await session.commit()
    return target


@router.delete("/targets/{target_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=Admin)
async def delete_target(target_id: uuid.UUID, session: Session):
    await _target_or_404(session, target_id)
    # Se borra en orden para no depender de ON DELETE CASCADE (SQLite en pruebas no lo aplica por defecto).
    for model in (db.Mention, db.ConnectorState, db.RiskSnapshot, db.SurveyResponse, db.AlertRecord):
        await session.execute(delete(model).where(model.target_id == target_id))
    await session.execute(delete(db.Target).where(db.Target.id == target_id))
    await session.commit()


# --- Menciones, riesgo y desglose -----------------------------------------------------------------


@router.get("/targets/{target_id}/mentions", response_model=list[MentionOut])
async def list_mentions(
    target_id: uuid.UUID, session: Session, source: str | None = None, sentiment: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
):
    q = select(db.Mention).where(db.Mention.target_id == target_id)
    if source:
        q = q.where(db.Mention.source == source)
    if sentiment:
        try:
            q = q.where(db.Mention.sentiment == Sentiment(sentiment.capitalize()).value)
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Sentimiento inválido") from None
    rows = (await session.scalars(q.order_by(db.Mention.published_at.desc()).limit(limit))).all()
    return [MentionOut.of(m) for m in rows]


@router.get("/targets/{target_id}/risk", response_model=list[RiskOut])
async def risk_series(target_id: uuid.UUID, session: Session, hours: Annotated[int, Query(ge=1, le=24 * 365)] = 24 * 7):
    since = datetime.now(UTC) - timedelta(hours=hours)
    R = db.RiskSnapshot
    rows = (await session.scalars(select(R).where(R.target_id == target_id, R.at >= since).order_by(R.at))).all()
    return [RiskOut.of(s) for s in rows]


@router.get("/targets/{target_id}/risk/latest", response_model=RiskOut)
async def risk_latest(target_id: uuid.UUID, session: Session):
    R = db.RiskSnapshot
    s = await session.scalar(select(R).where(R.target_id == target_id).order_by(R.at.desc()).limit(1))
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sin cálculo de riesgo todavía")
    return RiskOut.of(s)


@router.get("/targets/{target_id}/breakdown", response_model=BreakdownOut)
async def breakdown(target_id: uuid.UUID, session: Session, hours: Annotated[int, Query(ge=1, le=24 * 90)] = 24):
    since = datetime.now(UTC) - timedelta(hours=hours)
    M = db.Mention
    scope = (M.target_id == target_id, M.published_at >= since)

    by_source = (await session.execute(
        select(M.source, M.sentiment, func.count()).where(*scope).group_by(M.source, M.sentiment)
    )).all()
    negative = func.sum(case((M.sentiment == Sentiment.NEGATIVE.value, 1), else_=0))
    influencers = (await session.execute(
        select(M.author_handle, func.max(M.author_followers), func.count(), negative)
        .where(*scope).group_by(M.author_handle).order_by(func.max(M.author_followers).desc()).limit(10)
    )).all()
    topics = (await session.execute(
        select(M.topic, func.count()).where(*scope, M.topic.is_not(None))
        .group_by(M.topic).order_by(func.count().desc()).limit(20)
    )).all()
    return BreakdownOut(
        by_source_and_sentiment=[SourceSentimentCount(source=s, sentiment=sent, count=c) for s, sent, c in by_source],
        influencers=[Influencer(author=a, followers=f or 0, mentions=c, negative=n or 0) for a, f, c, n in influencers],
        topics=[TopicCount(topic=t, count=c) for t, c in topics],
    )


@router.get("/targets/{target_id}/alerts", response_model=list[AlertOut])
async def list_alerts(target_id: uuid.UUID, session: Session):
    A = db.AlertRecord
    rows = (await session.scalars(select(A).where(A.target_id == target_id).order_by(A.at.desc()).limit(50))).all()
    return [AlertOut.model_validate(a) for a in rows]


@router.get("/targets/{target_id}/connectors", response_model=list[ConnectorStateOut])
async def connector_states(target_id: uuid.UUID, session: Session):
    C = db.ConnectorState
    return (await session.scalars(select(C).where(C.target_id == target_id).order_by(C.source))).all()


@router.get("/sources", response_model=SourcesOut)
async def source_status(session: Session, request: Request):
    """Estado de cada fuente y canal de avisos: si tiene llave, cuándo corrió, qué trajo y qué objetivos fallan."""
    runtime = request.app.state.runtime
    configured: dict[str, bool] = {}
    for c in runtime.connectors:
        if c.source != "demo" or c.is_configured:
            configured[c.source] = c.is_configured
        if c.source == "bluesky":
            configured["bluesky-live"] = request.app.state.settings.connectors.jetstream.enabled

    C, M, T = db.ConnectorState, db.Mention, db.Target
    last_run = dict((await session.execute(select(C.source, func.max(C.last_run_at)).group_by(C.source))).all())
    errors: dict[str, list[SourceError]] = {}
    rows = await session.execute(
        select(C.source, C.target_id, T.name, C.last_run_at, C.last_error)
        .join(T, T.id == C.target_id).where(C.last_error.is_not(None)).order_by(T.name)
    )
    for source, target_id, name, at, error in rows:
        errors.setdefault(source, []).append(SourceError(target_id=target_id, target_name=name, at=at, error=error))
    since = datetime.now(UTC) - timedelta(hours=24)
    mentions = {
        source: (last, recent) for source, last, recent in await session.execute(
            select(M.source, func.max(M.ingested_at), func.count().filter(M.ingested_at >= since)).group_by(M.source)
        )
    }

    def status_of(source: str) -> SourceStatus:
        # Bluesky en vivo guarda sus menciones como "bluesky", igual que la búsqueda.
        key = "bluesky" if source == "bluesky-live" else source
        last_mention, recent = mentions.get(key, (None, 0))
        return SourceStatus(
            source=source, configured=configured[source], last_run_at=last_run.get(source),
            last_mention_at=last_mention, mentions_last_day=recent, errors=errors.get(source, []),
        )

    return SourcesOut(
        sources=[status_of(s) for s in configured],
        channels=[ChannelStatus(channel=n, configured=ok) for n, ok in runtime.notifier.status.items()],
    )


# --- Cuestionarios --------------------------------------------------------------------------------


def _catalog(request: Request) -> SurveyCatalog:
    return request.app.state.surveys


@router.post("/targets/{target_id}/survey-responses", response_model=SurveyResponseOut, dependencies=Analyst)
async def submit_survey(target_id: uuid.UUID, body: SurveySubmission, session: Session, request: Request):
    await _target_or_404(session, target_id)
    catalog = _catalog(request)
    survey = catalog.find(body.survey_id)
    if survey is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cuestionario desconocido.")
    problems = catalog.problems(survey, body.answers)
    if problems:
        raise HTTPException(422, {"message": "Respuestas incompletas o inválidas.", "problems": problems})
    result = catalog.score(survey, body.answers)
    row = db.SurveyResponse(
        id=uuid.uuid4(), target_id=target_id, survey_id=survey.id, submitted_at=datetime.now(UTC), answers=body.answers,
        score=None if result is None else round(result.score, 2),
        level=None if result is None else result.level.value,
        section_values={} if result is None else {s.section_id: s.value for s in result.sections},
    )
    session.add(row)
    await session.commit()
    if result is not None:
        await request.app.state.risk_engine.recompute(target_id)
    return row


@router.get("/targets/{target_id}/survey-responses", response_model=list[SurveyResponseOut])
async def list_survey_responses(
    target_id: uuid.UUID, session: Session, survey_id: Annotated[str | None, Query(alias="surveyId")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
):
    """Historial de respuestas, la más reciente primero (el tablero precarga el cuestionario con la primera)."""
    await _target_or_404(session, target_id)
    S = db.SurveyResponse
    q = select(S).where(S.target_id == target_id)
    if survey_id:
        q = q.where(S.survey_id == survey_id)
    return (await session.scalars(q.order_by(S.submitted_at.desc()).limit(limit))).all()


@router.get("/surveys", response_model=list[SurveySummary])
async def list_surveys(request: Request):
    return [
        SurveySummary(id=s.id, name=s.name, description=s.description, scored=s.scored, sections=len(s.sections))
        for s in _catalog(request).all
    ]


@router.get("/surveys/{survey_id}", response_model=SurveyDefinition)
async def get_survey(survey_id: str, request: Request):
    survey = _catalog(request).find(survey_id)
    if survey is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cuestionario no encontrado")
    return survey


# --- Tiempo real ----------------------------------------------------------------------------------

ws_router = APIRouter()


@ws_router.websocket("/ws/targets/{target_id}")
async def live(ws: WebSocket, target_id: uuid.UUID):
    try:
        await websocket_user(ws)
    except HTTPException:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)  # sin sesión o desde otro sitio
        return
    await ws.accept()
    hub = ws.app.state.hub
    hub.subscribe(target_id, ws)
    try:
        while True:
            await ws.receive_text()  # el cliente solo manda pings; mantiene la conexión abierta
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe(target_id, ws)
