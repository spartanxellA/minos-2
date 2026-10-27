"""Inicio de sesión con cuentas de minOS: correo y contraseña, sesión en una cookie HttpOnly.

- Contraseñas con scrypt (biblioteca estándar) y sal por cuenta.
- La sesión es un token aleatorio; en la base solo se guarda su SHA-256, con vencimiento. Cerrar sesión, desactivar
  la cuenta o cambiar la contraseña la invalida al momento.
- Tras varios intentos fallidos la cuenta se bloquea un rato.
- Las peticiones que cambian datos y el WebSocket solo se aceptan desde el mismo sitio o un origen permitido
  (además de SameSite=Lax en la cookie), para que otra página no pueda usarlas con la sesión del navegador.
- Roles: lector (ve todo), analista (además da de alta objetivos y contesta cuestionarios), administrador (además
  borra objetivos y administra cuentas).

Con MINOS_AUTH__MODE=off no se pide sesión; solo se permite en development.
"""
import base64
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, WebSocket, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from . import db
from .config import Settings


class Role(StrEnum):
    VIEWER = "viewer"
    ANALYST = "analyst"
    ADMIN = "admin"

    @property
    def rank(self) -> int:
        return list(Role).index(self)


ROLE_LABEL = {Role.VIEWER: "Lector", Role.ANALYST: "Analista", Role.ADMIN: "Administrador"}

# scrypt: n=2^15, r=8, p=1 (unos 32 MB y ~50 ms por intento).
_N, _R, _P = 2**15, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, maxmem=64 * 1024 * 1024)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${_N}${_R}${_P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, expected = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), maxmem=64 * 1024 * 1024
        )
        return hmac.compare_digest(digest, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


# Para comparar contra algo cuando el correo no existe y tardar lo mismo (no revela qué correos tienen cuenta).
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def normalize_email(email: str) -> str:
    return email.strip().lower()


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID | None
    email: str
    name: str
    role: Role

    def can(self, role: Role) -> bool:
        return self.role.rank >= role.rank


# Con el inicio de sesión apagado (development) todo se hace como este administrador.
DEV_USER = CurrentUser(None, "dev@localhost", "Desarrollo", Role.ADMIN)


def _settings(conn: Request | WebSocket) -> Settings:
    return conn.app.state.settings


def _same_origin(conn: Request | WebSocket) -> bool:
    origin = conn.headers.get("origin")
    if not origin:
        return True  # sin Origin: no es una petición de otro sitio hecha por un navegador
    if origin in _settings(conn).cors_origins:
        return True
    return urlsplit(origin).netloc == conn.headers.get("host", "")


async def _user_for_token(conn: Request | WebSocket, token: str | None) -> CurrentUser | None:
    if not token:
        return None
    async with conn.app.state.db.session() as session:
        row = (await session.execute(
            select(db.User, db.UserSession.expires_at)
            .join(db.UserSession, db.UserSession.user_id == db.User.id)
            .where(db.UserSession.token_hash == token_hash(token))
        )).first()
    if row is None:
        return None
    user, expires_at = row
    if not user.active or expires_at <= datetime.now(UTC):
        return None
    return CurrentUser(user.id, user.email, user.name, Role(user.role))


async def current_user(request: Request) -> CurrentUser:
    settings = _settings(request)
    if settings.auth.mode == "off":
        return DEV_USER
    if request.method not in ("GET", "HEAD", "OPTIONS") and not _same_origin(request):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Origen no permitido")
    user = await _user_for_token(request, request.cookies.get(settings.auth.cookie_name))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Inicia sesión")
    return user


def require_role(role: Role):
    async def check(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if not user.can(role):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Se necesita el rol {ROLE_LABEL[role]}")
        return user

    return check


async def websocket_user(ws: WebSocket) -> CurrentUser:
    """El navegador manda la cookie al abrir el WebSocket; se revisa también el origen."""
    settings = _settings(ws)
    if settings.auth.mode == "off":
        return DEV_USER
    if not _same_origin(ws):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Origen no permitido")
    user = await _user_for_token(ws, ws.cookies.get(settings.auth.cookie_name))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Inicia sesión")
    return user


async def create_user(session: AsyncSession, email: str, name: str, role: Role, password: str) -> db.User:
    user = db.User(
        id=uuid.uuid4(), email=normalize_email(email), name=name.strip() or normalize_email(email), role=role.value,
        password_hash=hash_password(password), active=True, failed_logins=0, created_at=datetime.now(UTC),
    )
    session.add(user)
    return user


async def end_sessions(session: AsyncSession, user_id: uuid.UUID, keep: str | None = None) -> None:
    q = delete(db.UserSession).where(db.UserSession.user_id == user_id)
    if keep:
        q = q.where(db.UserSession.token_hash != keep)
    await session.execute(q)


async def bootstrap_admin(database: db.Database, settings: Settings) -> bool:
    """Crea el primer administrador desde la configuración si todavía no hay cuentas."""
    from . import audit  # audit importa este módulo

    a = settings.auth
    if a.mode != "local" or not (a.bootstrap_admin_email and a.bootstrap_admin_password):
        return False
    async with database.session() as session:
        if await session.scalar(select(db.User.id).limit(1)) is not None:
            return False
        user = await create_user(session, a.bootstrap_admin_email, "Administrador", Role.ADMIN, a.bootstrap_admin_password)
        audit.record(session, None, "user.created", audit.SYSTEM, entity_type="user", entity_id=user.id,
                     entity_label=user.email, changes=audit.diff({}, audit.user_snapshot(user)),
                     detail={"via": "MINOS_AUTH__BOOTSTRAP_ADMIN_EMAIL"})
        try:
            await session.commit()
        except IntegrityError:  # otra réplica de la API lo creó al mismo tiempo
            return False
    return True
