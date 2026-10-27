"""Rutas de listas negras: resultado por objetivo, revisión de coincidencias y listas propias."""
import hashlib
import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit, db
from ..auth import CurrentUser, Role, current_user, require_role
from ..domain.screening import ascii_fold
from .schemas import CustomListInput, CustomListResult, MatchOut, ReviewInput, ScreeningOut, WatchlistOut
from .screener import screening_summary
from .sources import CATEGORY_LABEL, OFFICIAL_SOURCES, parse_custom_csv
from .sync import save_list


async def get_session(request: Request):
    async with request.app.state.db.session() as session:
        yield session


Session = Annotated[AsyncSession, Depends(get_session)]
Me = Annotated[CurrentUser, Depends(current_user)]
Analyst = Annotated[CurrentUser, Depends(require_role(Role.ANALYST))]
Admin = Annotated[CurrentUser, Depends(require_role(Role.ADMIN))]
watchlist_router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


@watchlist_router.get("/targets/{target_id}/screening", response_model=ScreeningOut)
async def target_screening(target_id: uuid.UUID, session: Session):
    if await session.get(db.Target, target_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Objetivo no encontrado")
    return await screening_summary(session, target_id)


@watchlist_router.get("/screening/matches", response_model=list[MatchOut])
async def list_matches(
    session: Session, match_status: Annotated[Literal["pending", "confirmed", "dismissed"], Query(alias="status")] = "pending",
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
):
    """Coincidencias vigentes de todos los objetivos (por omisión, las pendientes de revisar)."""
    S, T = db.ScreeningMatch, db.Target
    rows = (await session.execute(
        select(S, T.name).join(T, T.id == S.target_id).where(S.status == match_status, S.active.is_(True))
        .order_by(S.score.desc(), S.first_seen_at.desc()).limit(limit)
    )).all()
    return [MatchOut.of(m, name) for m, name in rows]


@watchlist_router.post("/screening/matches/{match_id}/review", response_model=MatchOut)
async def review_match(match_id: int, body: ReviewInput, session: Session, request: Request, me: Analyst):
    m = await session.get(db.ScreeningMatch, match_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Coincidencia no encontrada")
    note = body.note.strip()
    if body.decision != "pending" and len(note) < 3:
        raise HTTPException(422, "Escribe una nota con el motivo de la decisión.")
    target = await session.get(db.Target, m.target_id)
    before = m.status
    m.status, m.review_note = body.decision, note or None
    m.reviewed_at, m.reviewed_by_id, m.reviewed_by_email = datetime.now(UTC), me.id, me.email
    audit.record(session, request, "screening.reviewed", me, entity_type="target", entity_id=m.target_id,
                 entity_label=target.name if target else None, changes={"status": [before, m.status]},
                 detail={"matchId": m.id, "list": m.source_name, "listedName": m.listed_name, "score": m.score,
                         "note": note})
    await session.commit()
    if before == "confirmed" or m.status == "confirmed":
        await request.app.state.risk_engine.recompute(m.target_id)
    summary = await screening_summary(session, m.target_id)
    await request.app.state.bus.publish(m.target_id, "screeningUpdated", summary)
    return MatchOut.of(m, target.name if target else None)


@watchlist_router.get("/watchlists", response_model=list[WatchlistOut])
async def list_watchlists(session: Session, request: Request):
    settings = request.app.state.settings.watchlists
    rows = {r.slug: r for r in (await session.scalars(select(db.WatchlistSource))).all()}
    out = []
    for slug, src in OFFICIAL_SOURCES.items():
        r = rows.pop(slug, None)
        out.append(WatchlistOut(
            slug=slug, name=src.name, publisher=src.publisher, category=src.category,
            category_label=CATEGORY_LABEL[src.category], custom=False, enabled=settings.enabled and slug in settings.sources,
            configured=slug != "worldbank" or bool(settings.worldbank_api_key), info_url=src.info_url,
            license=src.license, **_state(r),
        ))
    for r in sorted(rows.values(), key=lambda r: r.name.lower()):
        out.append(WatchlistOut(
            slug=r.slug, name=r.name, publisher="Lista propia", category=r.category,
            category_label=CATEGORY_LABEL.get(r.category, r.category), custom=True, enabled=True, **_state(r),
        ))
    return out


def _state(r: db.WatchlistSource | None) -> dict:
    if r is None:
        return {}
    return {"entry_count": r.entry_count, "last_checked_at": r.last_checked_at, "last_changed_at": r.last_changed_at,
            "last_error": r.last_error, "uploaded_by": r.uploaded_by}


def custom_slug(name: str) -> str:
    return "propia-" + (re.sub(r"[^a-z0-9]+", "-", ascii_fold(name)).strip("-")[:50] or "lista")


@watchlist_router.post("/watchlists/custom", response_model=CustomListResult, status_code=status.HTTP_201_CREATED)
async def upload_custom(body: CustomListInput, session: Session, request: Request, me: Admin):
    """Carga o reemplaza una lista propia (PEP, UIF, SESNA…) desde un CSV. Una lista con el mismo nombre se reemplaza."""
    slug = custom_slug(body.name)
    data = body.csv.encode("utf-8")
    try:
        records = list(parse_custom_csv(data, slug))
    except ValueError as ex:
        raise HTTPException(422, str(ex)) from None
    if not records:
        raise HTTPException(422, "El archivo no tiene filas con nombre.")
    counts = await save_list(request.app.state.db, slug, records, hashlib.sha256(data).hexdigest(), datetime.now(UTC),
                             name=body.name.strip(), category=body.category, uploaded_by=me.email)
    audit.record(session, request, "watchlist.uploaded", me, entity_type="watchlist", entity_id=slug,
                 entity_label=body.name.strip(), detail={"category": body.category, "entries": counts[0],
                                                         "added": counts[1], "changed": counts[2], "removed": counts[3]})
    await session.commit()
    return CustomListResult(slug=slug, entries=counts[0], added=counts[1], changed=counts[2], removed=counts[3])


@watchlist_router.delete("/watchlists/custom/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom(slug: str, session: Session, request: Request, me: Admin):
    row = await session.get(db.WatchlistSource, slug)
    if row is None or not row.custom:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lista propia no encontrada")
    S = db.ScreeningMatch
    affected = set((await session.scalars(
        select(S.target_id).where(S.source == slug, S.status == "confirmed", S.active.is_(True))
    )).all())
    await session.execute(update(S).where(S.source == slug).values(active=False))
    await session.execute(delete(db.WatchlistEntry).where(db.WatchlistEntry.source == slug))
    await session.execute(delete(db.WatchlistSource).where(db.WatchlistSource.slug == slug))
    audit.record(session, request, "watchlist.deleted", me, entity_type="watchlist", entity_id=slug,
                 entity_label=row.name, detail={"entries": row.entry_count})
    await session.commit()
    for target_id in affected:
        await request.app.state.risk_engine.recompute(target_id)
