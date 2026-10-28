"""Auditoría: quién hizo qué, cuándo y desde dónde.

Cada cambio se registra en la misma transacción que el cambio en sí (si uno falla, no queda ninguno). Se registran
los inicios de sesión (también los fallidos y los bloqueos), las cuentas y sus roles, los objetivos y los
cuestionarios, con los valores de antes y después. Nunca se guardan contraseñas ni tokens.

La bitácora solo la ven los administradores (GET /api/audit) y la API no tiene forma de cambiarla ni borrarla.
"""
import csv
import io
import json
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import db
from .auth import CurrentUser, Role, require_role
from .schemas import Camel

# Acción → descripción para el tablero y el CSV.
ACTIONS = {
    "auth.login": "Inicio de sesión",
    "auth.login_failed": "Inicio de sesión fallido",
    "auth.locked": "Cuenta bloqueada por intentos",
    "auth.logout": "Cierre de sesión",
    "auth.password_changed": "Cambio de contraseña propia",
    "user.created": "Cuenta creada",
    "user.updated": "Cuenta modificada",
    "user.deleted": "Cuenta borrada",
    "target.created": "Objetivo creado",
    "target.updated": "Objetivo modificado",
    "target.deactivated": "Objetivo dado de baja",
    "target.reactivated": "Objetivo reactivado",
    "target.deleted": "Objetivo borrado definitivamente",
    "survey.submitted": "Cuestionario contestado",
    "audit.exported": "Bitácora exportada",
    "screening.reviewed": "Coincidencia en lista revisada",
    "watchlist.uploaded": "Lista propia cargada",
    "watchlist.deleted": "Lista propia borrada",
}

# Quien actúa sin sesión: la terminal del servidor (python -m minos.users) o el arranque (primer administrador).
SYSTEM = CurrentUser(None, "sistema", "Sistema", Role.ADMIN)


def client_ip(request: Request | None) -> str | None:
    # Detrás de Caddy, uvicorn --proxy-headers ya pone aquí la IP real tomada de X-Forwarded-For.
    return request.client.host if request is not None and request.client else None


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, list[Any]]:
    """Campos que cambiaron, como {campo: [antes, después]}."""
    return {k: [before.get(k), after.get(k)] for k in sorted(before.keys() | after.keys()) if before.get(k) != after.get(k)}


def target_snapshot(t: db.Target) -> dict[str, Any]:
    return {
        "name": t.name, "kind": t.kind, "aliases": list(t.aliases or []), "keywords": list(t.keywords or []),
        "excludedTerms": list(t.excluded_terms or []), "handles": dict(t.handles or {}), "enabled": t.enabled,
        "birthDate": t.birth_date, "nationality": t.nationality, "identifiers": dict(t.identifiers or {}),
    }


def user_snapshot(u: db.User) -> dict[str, Any]:
    return {"email": u.email, "name": u.name, "role": u.role, "active": u.active}


def record(
    session: AsyncSession, request: Request | None, action: str, actor: CurrentUser | None = None, *,
    actor_email: str | None = None, success: bool = True, entity_type: str | None = None,
    entity_id: uuid.UUID | str | None = None, entity_label: str | None = None,
    changes: dict[str, list[Any]] | None = None, detail: dict[str, Any] | None = None,
) -> db.AuditEvent:
    """Agrega el evento a la sesión; se guarda con el siguiente commit."""
    assert action in ACTIONS, action
    user_agent = request.headers.get("user-agent") if request is not None else None
    event = db.AuditEvent(
        at=db.utcnow(), action=action, success=success,
        actor_id=actor.id if actor else None,
        actor_email=(actor_email or (actor.email if actor else None) or "")[:254] or None,
        actor_role=actor.role.value if actor and actor is not SYSTEM else None,
        entity_type=entity_type, entity_id=None if entity_id is None else str(entity_id),
        entity_label=entity_label[:254] if entity_label else None,
        changes=changes or None, detail=detail or None,
        ip=(client_ip(request) or "")[:64] or None, user_agent=user_agent[:300] if user_agent else None,
    )
    session.add(event)
    return event


# --- Consulta (solo administradores) --------------------------------------------------------------


class AuditEventOut(Camel):
    id: int
    at: datetime
    actor_id: uuid.UUID | None
    actor_email: str | None
    actor_role: str | None
    action: str
    action_label: str
    success: bool
    entity_type: str | None
    entity_id: str | None
    entity_label: str | None
    changes: dict[str, list[Any]] | None
    detail: dict[str, Any] | None
    ip: str | None
    user_agent: str | None

    @classmethod
    def of(cls, e: db.AuditEvent) -> "AuditEventOut":
        return cls.model_validate({**{c: getattr(e, c) for c in cls.model_fields if c != "action_label"},
                                   "action_label": ACTIONS.get(e.action, e.action)})


class AuditPage(Camel):
    events: list[AuditEventOut]
    # Para la siguiente página: pasar como ?before=…
    next_before: int | None
    actions: dict[str, str]


async def get_session(request: Request):
    async with request.app.state.db.session() as session:
        yield session


Session = Annotated[AsyncSession, Depends(get_session)]
audit_router = APIRouter(prefix="/api/audit")
Admin = Annotated[CurrentUser, Depends(require_role(Role.ADMIN))]


class AuditFilters:
    def __init__(
        self,
        action: Annotated[str | None, Query(description="acción exacta (auth.login) o prefijo (auth.)")] = None,
        actor: Annotated[str | None, Query(description="parte del correo de quien actuó")] = None,
        actor_id: Annotated[uuid.UUID | None, Query(alias="actorId")] = None,
        entity_type: Annotated[str | None, Query(alias="entityType")] = None,
        entity_id: Annotated[str | None, Query(alias="entityId")] = None,
        success: bool | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        q: Annotated[str | None, Query(max_length=200, description="busca en correo, objeto afectado e IP")] = None,
    ):
        self.action, self.actor, self.actor_id, self.entity_type, self.entity_id = action, actor, actor_id, entity_type, entity_id
        self.success, self.since, self.until, self.q = success, since, until, q

    def apply(self, query):
        E = db.AuditEvent
        if self.action:
            query = query.where(E.action.startswith(self.action, autoescape=True) if self.action.endswith(".")
                                else E.action == self.action)
        if self.actor:
            query = query.where(E.actor_email.icontains(self.actor.strip(), autoescape=True))
        if self.actor_id:
            query = query.where(E.actor_id == self.actor_id)
        if self.entity_type:
            query = query.where(E.entity_type == self.entity_type)
        if self.entity_id:
            query = query.where(E.entity_id == self.entity_id)
        if self.success is not None:
            query = query.where(E.success.is_(self.success))
        if self.since:
            query = query.where(E.at >= self.since)
        if self.until:
            query = query.where(E.at < self.until)
        if self.q and self.q.strip():
            text = self.q.strip()
            query = query.where(or_(*(c.icontains(text, autoescape=True) for c in (E.actor_email, E.entity_label, E.ip))))
        return query


Filters = Annotated[AuditFilters, Depends()]


@audit_router.get("", response_model=AuditPage)
async def list_events(
    session: Session, _: Admin, filters: Filters, before: int | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    """Eventos del más reciente al más antiguo, con filtros y paginación por id."""
    E = db.AuditEvent
    query = filters.apply(select(E))
    if before is not None:
        query = query.where(E.id < before)
    rows = (await session.scalars(query.order_by(E.id.desc()).limit(limit + 1))).all()
    more = len(rows) > limit
    rows = rows[:limit]
    return AuditPage(events=[AuditEventOut.of(e) for e in rows], next_before=rows[-1].id if more else None, actions=ACTIONS)


EXPORT_LIMIT = 50_000


@audit_router.get("/export.csv")
async def export_csv(session: Session, me: Admin, filters: Filters, request: Request):
    """La bitácora filtrada en CSV (hasta 50 000 filas), para archivarla o abrirla en Excel."""
    E = db.AuditEvent
    rows = (await session.scalars(filters.apply(select(E)).order_by(E.id.desc()).limit(EXPORT_LIMIT))).all()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["id", "fecha_utc", "usuario", "rol", "accion", "descripcion", "resultado", "tipo", "id_afectado",
                "afectado", "cambios", "detalle", "ip", "navegador"])
    for e in rows:
        w.writerow([_cell(v) for v in (
            e.id, e.at.isoformat(), e.actor_email or "", e.actor_role or "", e.action, ACTIONS.get(e.action, e.action),
            "ok" if e.success else "fallo", e.entity_type or "", e.entity_id or "", e.entity_label or "",
            _compact(e.changes), _compact(e.detail), e.ip, e.user_agent,
        )])
    record(session, request, "audit.exported", me, detail={"rows": len(rows)})
    await session.commit()
    stamp = db.utcnow().strftime("%Y%m%d-%H%M")
    # BOM para que Excel reconozca los acentos.
    return Response("﻿" + out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"content-disposition": f'attachment; filename="minos-auditoria-{stamp}.csv"'})


def _compact(value: dict | None) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")) if value else ""


def _cell(value: object) -> str:
    """Evita que Excel interprete como fórmula un texto que escribió un usuario (=, +, -, @)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text
