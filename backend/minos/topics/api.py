import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import db
from ..auth import current_user
from ..domain.mentions import Sentiment
from ..schemas import Camel
from .extract import TermKind, extract_topics, name_words

# Se leen a lo más las menciones más recientes del periodo; alcanza para ver de qué se habla sin cargar todo.
MAX_MENTIONS = 5000


class TopicTerm(Camel):
    term: str
    kind: TermKind
    # En cuántas menciones aparece.
    count: int
    positive: int
    negative: int


class TopicsOverview(Camel):
    days: int
    # Menciones del periodo (con los filtros) y cuántas se leyeron; si son menos, se tomaron las más recientes.
    total: int
    analyzed: int
    terms: list[TopicTerm]


async def get_session(request: Request):
    async with request.app.state.db.session() as session:
        yield session


topics_router = APIRouter(prefix="/api/targets/{target_id}/topics", dependencies=[Depends(current_user)])


@topics_router.get("", response_model=TopicsOverview)
async def topics_overview(
    target_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    source: str | None = None,
    sentiment: Literal["negative", "neutral", "positive"] | None = None,
    limit: Annotated[int, Query(ge=10, le=150)] = 80,
):
    """Palabras, frases y hashtags más mencionados sobre el objetivo en los últimos `days` días."""
    target = await session.get(db.Target, target_id)
    if target is None:
        raise HTTPException(404, "Objetivo no encontrado")
    M = db.Mention
    scope = [M.target_id == target_id, M.published_at >= datetime.now(UTC) - timedelta(days=days)]
    if source:
        scope.append(M.source == source)
    if sentiment:
        scope.append(M.sentiment == Sentiment(sentiment.capitalize()).value)

    total = await session.scalar(select(func.count()).select_from(M).where(*scope)) or 0
    rows = (await session.execute(
        select(M.text, M.sentiment).where(*scope).order_by(M.published_at.desc()).limit(MAX_MENTIONS)
    )).all()
    exclude = name_words([target.name, *(target.aliases or []), *(target.handles or {}).values()])
    analyzed, terms = extract_topics(((text, s) for text, s in rows), exclude, limit)
    return TopicsOverview(
        days=days, total=total, analyzed=analyzed,
        terms=[TopicTerm(term=t.term, kind=t.kind, count=t.count, positive=t.positive, negative=t.negative) for t in terms],
    )
