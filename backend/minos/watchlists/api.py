"""Rutas de listas negras: resultado por objetivo, revisión de coincidencias y listas propias."""
import csv
import hashlib
import io
import re
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit, db
from ..audit import _cell
from ..auth import CurrentUser, Role, current_user, require_role
from ..domain.screening import EntryKind, ascii_fold
from .schemas import (
    ChangeOut, CustomListInput, CustomListResult, MatchOut, ReviewInput, ScreeningOut, UploadOut, WatchlistOut,
)
from .screener import screening_summary
from .sources import CATEGORY_LABEL, OFFICIAL_SOURCES, parse_custom_csv
from .sync import batches, save_list


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
        select(S, T.name).join(T, T.id == S.target_id).where(S.status == match_status, S.active.is_(True), T.enabled.is_(True))
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


# Una lista PEP nacional completa pesa cerca de 100 MB.
MAX_UPLOAD_BYTES = 300 * 1024 * 1024


@watchlist_router.post("/watchlists/custom", response_model=CustomListResult, status_code=status.HTTP_201_CREATED)
async def upload_custom(body: CustomListInput, session: Session, request: Request, me: Admin):
    """Carga una lista propia (PEP, UIF, SESNA…) desde un CSV. En modo full una lista con el mismo nombre se
    reemplaza; en modo update solo se agregan y actualizan los registros del archivo."""
    return await _save_custom(body.name, body.category, body.csv.encode("utf-8"), session, request, me,
                              mode=body.mode, file_name=body.file_name)


@watchlist_router.post("/watchlists/custom/file", response_model=CustomListResult, status_code=status.HTTP_201_CREATED)
async def upload_custom_file(
    session: Session, request: Request, me: Admin, name: Annotated[str, Query(min_length=2, max_length=200)],
    category: Annotated[Literal["pep", "sanctions", "tax", "debarment", "other"], Query()] = "pep",
    mode: Annotated[Literal["full", "update"], Query()] = "full",
    file_name: Annotated[str | None, Query(alias="fileName", max_length=255)] = None,
):
    """Lo mismo, con el archivo tal cual en el cuerpo (sin JSON): así entran listas de cientos de MB."""
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                                f"El archivo pasa de {MAX_UPLOAD_BYTES // 2**20} MB.")
    return await _save_custom(name, category, bytes(data), session, request, me, mode=mode, file_name=file_name)


async def _save_custom(name: str, category: str, data: bytes, session: AsyncSession, request: Request,
                       me: CurrentUser, *, mode: str = "full", file_name: str | None = None) -> CustomListResult:
    name = name.strip()
    slug = custom_slug(name)
    if mode == "update":
        current = await session.get(db.WatchlistSource, slug)
        if current is None or not current.custom:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                f"No existe la lista «{name}». Carga primero la lista completa y después sus "
                                "actualizaciones.")
        # Una actualización conserva el nombre y el tipo de la lista.
        name, category = current.name, current.category
    records = parse_custom_csv(data, slug)
    if category == "pep":
        # Una lista PEP es de personas, aunque el archivo no traiga tipo, RFC ni CURP.
        records = (replace(r, kind=EntryKind.PERSON) if r.kind == EntryKind.OTHER else r for r in records)
    chunks = batches(records)
    try:
        # La primera tanda se lee antes de tocar la base: un archivo sin encabezado o sin nombres no borra la lista.
        first = await anext(chunks, [])
    except ValueError as ex:
        raise HTTPException(422, str(ex)) from None
    if not first:
        raise HTTPException(422, "El archivo no tiene filas con nombre.")

    async def all_chunks():
        yield first
        async for chunk in chunks:
            yield chunk

    c, upload_id = await save_list(request.app.state.db, slug, all_chunks(), hashlib.sha256(data).hexdigest(),
                                   datetime.now(UTC), name=name, category=category, uploaded_by=me.email, mode=mode,
                                   file_name=file_name)
    audit.record(session, request, "watchlist.updated" if mode == "update" else "watchlist.uploaded", me,
                 entity_type="watchlist", entity_id=slug, entity_label=name,
                 detail={"category": category, "mode": mode, "file": file_name, "uploadId": upload_id,
                         "rows": c.rows, "entries": c.entries, "added": c.added, "changed": c.changed,
                         "statusChanged": c.status_changed, "unchanged": c.unchanged, "removed": c.removed})
    await session.commit()
    return CustomListResult(slug=slug, mode=mode, upload_id=upload_id, rows=c.rows, entries=c.entries, added=c.added,
                            changed=c.changed, status_changed=c.status_changed, unchanged=c.unchanged,
                            removed=c.removed)


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


@watchlist_router.get("/watchlists/custom/{slug}/uploads", response_model=list[UploadOut])
async def list_uploads(slug: str, session: Session, limit: Annotated[int, Query(ge=1, le=200)] = 50):
    """Cargas de una lista propia, la más reciente primero: completas y de actualización, con sus conteos."""
    if await session.get(db.WatchlistSource, slug) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lista no encontrada")
    U = db.WatchlistUpload
    rows = (await session.scalars(select(U).where(U.source == slug).order_by(U.at.desc(), U.id.desc()).limit(limit))).all()
    return [UploadOut.model_validate(u) for u in rows]


CHANGE_LABEL = {"added": "Alta", "status": "Cambio de estatus", "changed": "Otro cambio", "removed": "Retirado"}
FIELD_LABEL = {"status": "Estatus", "name": "Nombre", "programs": "Cargo", "birth_dates": "Nacimiento",
               "identifiers": "Documentos", "nationalities": "País", "aliases": "Alias"}


def _plain(v) -> str:
    if v is None:
        return ""
    return " · ".join(str(x) for x in v) if isinstance(v, list) else str(v)


@watchlist_router.get("/watchlists/uploads/{upload_id}/changes.csv")
async def upload_changes_csv(upload_id: int, session: Session, request: Request, me: Analyst):
    """Detalle de una carga en CSV: cada alta, cambio de estatus, otro cambio o retiro, con el antes y el después."""
    upload = await session.get(db.WatchlistUpload, upload_id)
    if upload is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Carga no encontrada")
    C = db.WatchlistChange
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["cambio", "nombre", "llave", "campo", "antes", "despues"])
    result = await session.stream_scalars(select(C).where(C.upload_id == upload_id).order_by(C.id))
    async for c in result:
        fields = c.fields or {}
        if not fields:
            w.writerow([_cell(x) for x in (CHANGE_LABEL.get(c.change, c.change), c.name, c.external_id, "", "", "")])
        for f, (before, after) in fields.items():
            w.writerow([_cell(x) for x in (CHANGE_LABEL.get(c.change, c.change), c.name, c.external_id,
                                           FIELD_LABEL.get(f, f), _plain(before), _plain(after))])
    stamp = upload.at.strftime("%Y%m%d-%H%M")
    return Response("\ufeff" + out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"content-disposition": f'attachment; filename="minos-{upload.source}-{stamp}.csv"'})


@watchlist_router.get("/screening/matches/{match_id}/history", response_model=list[ChangeOut])
async def match_history(match_id: int, session: Session):
    """Historial en la lista del registro de una coincidencia (altas, cambios de estatus y de cargo)."""
    m = await session.get(db.ScreeningMatch, match_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Coincidencia no encontrada")
    C, U = db.WatchlistChange, db.WatchlistUpload
    rows = (await session.execute(
        select(C, U.file_name, U.mode).join(U, U.id == C.upload_id)
        .where(C.source == m.source, C.external_id == m.external_id).order_by(C.at.desc(), C.id.desc()).limit(100)
    )).all()
    return [ChangeOut(at=c.at, change=c.change, name=c.name, fields=c.fields or {}, file_name=file_name, mode=mode)
            for c, file_name, mode in rows]
