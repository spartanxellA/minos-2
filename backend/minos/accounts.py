"""Rutas de inicio de sesión (/api/auth) y de administración de cuentas (/api/users)."""
import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from . import audit, db
from .auth import (
    _DUMMY_HASH, ROLE_LABEL, CurrentUser, Role, active_user, close_idle_session, create_user, current_user,
    end_sessions, hash_password, new_session_token, normalize_email, require_role, token_hash, verify_password,
)
from .login_guard import LoginGuard, Trip
from .notifications import SecurityNotice
from .schemas import Camel


async def get_session(request: Request):
    async with request.app.state.db.session() as session:
        yield session


Session = Annotated[AsyncSession, Depends(get_session)]
auth_router = APIRouter(prefix="/api/auth")
users_router = APIRouter(prefix="/api/users", dependencies=[Depends(require_role(Role.ADMIN))])
Admin = Annotated[CurrentUser, Depends(require_role(Role.ADMIN))]


class LoginInput(Camel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=500)


class PasswordChange(Camel):
    current_password: str = Field(max_length=500)
    new_password: str = Field(max_length=500)


class UserOut(Camel):
    id: uuid.UUID | None
    email: str
    name: str
    role: Role
    role_label: str
    active: bool = True
    last_login_at: datetime | None = None

    @classmethod
    def of(cls, u: db.User | CurrentUser) -> "UserOut":
        role = Role(u.role)
        return cls(
            id=u.id, email=u.email, name=u.name, role=role, role_label=ROLE_LABEL[role],
            active=getattr(u, "active", True), last_login_at=getattr(u, "last_login_at", None),
        )


class MeOut(UserOut):
    auth_mode: str
    # El tablero cierra la sesión tras este lapso sin actividad y avisa antes. None = nunca.
    idle_timeout_seconds: int | None = None
    # Idioma guardado en la cuenta; None = la persona no ha elegido (el tablero usa el del navegador).
    language: str | None = None


# Idiomas del tablero; los textos se traducen en el navegador.
Language = Literal["es", "en", "fr"]


class PreferencesInput(Camel):
    language: Language


class LogoutInput(Camel):
    # "idle": el tablero cerró la sesión porque la persona dejó de usarlo.
    reason: Literal["user", "idle"] = "user"


def _me_out(request: Request, user: db.User | CurrentUser) -> MeOut:
    a = request.app.state.settings.auth
    idle = int(a.idle_timeout.total_seconds()) if a.mode == "local" and a.idle_timeout else None
    return MeOut(**UserOut.of(user).model_dump(), auth_mode=a.mode, idle_timeout_seconds=idle,
                 language=getattr(user, "language", None))


class UserCreate(Camel):
    email: str = Field(min_length=3, max_length=254)
    name: str = Field(default="", max_length=200)
    role: Role = Role.VIEWER
    password: str = Field(max_length=500)


class UserUpdate(Camel):
    name: str | None = Field(default=None, max_length=200)
    role: Role | None = None
    active: bool | None = None
    password: str | None = Field(default=None, max_length=500)


def _check_password(request: Request, password: str) -> None:
    minimum = request.app.state.settings.auth.min_password_length
    if len(password) < minimum:
        raise HTTPException(422, f"La contraseña debe tener al menos {minimum} caracteres.")


def _check_email(email: str) -> str:
    email = normalize_email(email)
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(422, "Correo inválido.")
    return email


# --- Sesión ---------------------------------------------------------------------------------------


@auth_router.post("/login", response_model=MeOut)
async def login(body: LoginInput, request: Request, response: Response, session: Session):
    settings = request.app.state.settings
    a = settings.auth
    if a.mode == "off":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El inicio de sesión está apagado.")
    now = datetime.now(UTC)
    email = normalize_email(body.email)
    user = await session.scalar(select(db.User).where(db.User.email == email))

    ip = audit.client_ip(request) or "desconocida"
    guard = login_guard(request)

    def failed(reason: str) -> None:
        # Sin sesión no se sabe quién es: se anota el correo que escribió, no la cuenta como autora.
        audit.record(session, request, "auth.login_failed", actor_email=email, success=False,
                     entity_type="user", entity_id=user and user.id, entity_label=email, detail={"reason": reason})

    def too_many(seconds: int) -> HTTPException:
        # Mismo mensaje para correos con y sin cuenta y para bloqueos por correo o por IP.
        minutes = max(math.ceil(seconds / 60), 1)
        return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"Demasiados intentos. Vuelve a intentar en {minutes} min.",
                             headers={"Retry-After": str(max(seconds, 1))})

    blocked = await guard.retry_after(email, ip)
    if blocked is None and user is not None and user.locked_until and user.locked_until > now:
        blocked = ("locked", math.ceil((user.locked_until - now).total_seconds()))  # bloqueo guardado por versiones anteriores
    if blocked is not None:
        failed(blocked[0])
        await session.commit()
        raise too_many(blocked[1])

    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if user is None or not ok or not user.active:
        failed("unknown_account" if user is None else "wrong_password" if not ok else "inactive")
        for trip in await guard.failure(email, ip):
            until = (now + timedelta(seconds=trip.seconds)).isoformat()
            if trip.scope == "ip":
                audit.record(session, request, "auth.ip_blocked", actor_email=email, success=False,
                             entity_type="ip", entity_label=ip, detail={"until": until})
            else:
                audit.record(session, request, "auth.locked", actor_email=email, success=False, entity_type="user",
                             entity_id=user and user.id, entity_label=email, detail={"until": until, "scope": trip.scope})
            if trip.scope != "pair":
                await _security_alert(request, guard, trip, email, ip, now)
        await session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Correo o contraseña incorrectos.")

    await guard.success(email, ip)
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    token = new_session_token()
    session.add(db.UserSession(token_hash=token_hash(token), user_id=user.id, created_at=now, last_seen_at=now,
                               expires_at=now + a.session_ttl))
    await session.execute(delete(db.UserSession).where(db.UserSession.expires_at <= now))
    await _close_abandoned_sessions(session, request, now)
    audit.record(session, request, "auth.login", _actor(user), entity_type="user", entity_id=user.id, entity_label=user.email)
    await session.commit()
    response.set_cookie(
        a.cookie_name, token, max_age=int(a.session_ttl.total_seconds()), httponly=True, samesite="lax",
        secure=not settings.is_development, path="/",
    )
    return _me_out(request, user)


def login_guard(request: Request) -> LoginGuard:
    return LoginGuard(request.app.state.bus, request.app.state.settings.auth)


async def _security_alert(request: Request, guard: LoginGuard, trip: Trip, email: str, ip: str, now: datetime) -> None:
    """Avisa por los canales de notificaciones (correo, webhook, WhatsApp) de un bloqueo por correo o por IP."""
    runtime = getattr(request.app.state, "runtime", None)
    notifier = runtime and runtime.notifier
    if notifier is None or not notifier.channels or not await guard.may_alert():
        return
    a = request.app.state.settings.auth
    minutes = math.ceil(trip.seconds / 60)
    if trip.scope == "ip":
        title = "IP bloqueada por intentos de inicio de sesión"
        message = (f"La IP {ip} falló {a.ip_max_failed_logins} inicios de sesión en "
                   f"{math.ceil(a.ip_window.total_seconds() / 60)} min (último correo probado: {email}). "
                   f"Queda bloqueada {minutes} min.")
    else:
        title = "Correo bloqueado por intentos de inicio de sesión"
        message = (f"El correo {email} tuvo {a.account_max_failed_logins} intentos fallidos en "
                   f"{math.ceil(a.account_window.total_seconds() / 60)} min desde varias IP (la última: {ip}). "
                   f"Queda bloqueado {minutes} min.")
    notifier.dispatch([SecurityNotice(at=now, kind=f"login.{trip.scope}", title=title, message=message,
                                      dashboard_url=notifier.home_link)])


async def _close_abandoned_sessions(session: AsyncSession, request: Request, now: datetime) -> None:
    """Sesiones que se quedaron sin actividad y nadie volvió a usar (se cerró la pestaña): se cierran y se anotan."""
    idle_timeout = request.app.state.settings.auth.idle_timeout
    if not idle_timeout:
        return
    S = db.UserSession
    cutoff = now - idle_timeout
    rows = (await session.execute(
        select(db.User, S).join(S, S.user_id == db.User.id)
        .where(or_(S.last_seen_at < cutoff, S.last_seen_at.is_(None) & (S.created_at < cutoff)))
        .limit(500)
    )).all()
    for user, user_session in rows:
        await close_idle_session(session, None, user, user_session, via="cleanup")


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, session: Session, body: LogoutInput | None = None):
    a = request.app.state.settings.auth
    token = request.cookies.get(a.cookie_name)
    if token:
        row = (await session.execute(
            select(db.User, db.UserSession).join(db.UserSession, db.UserSession.user_id == db.User.id)
            .where(db.UserSession.token_hash == token_hash(token))
        )).first()
        if row is not None and body is not None and body.reason == "idle":
            await close_idle_session(session, request, *row, via="dashboard")
        else:
            result = await session.execute(delete(db.UserSession).where(db.UserSession.token_hash == token_hash(token)))
            if row is not None and result.rowcount:
                user = row[0]
                audit.record(session, request, "auth.logout", _actor(user), entity_type="user", entity_id=user.id,
                             entity_label=user.email)
        await session.commit()
    response.delete_cookie(a.cookie_name, path="/")


@auth_router.get("/me", response_model=MeOut)
async def me(request: Request, user: Annotated[CurrentUser, Depends(active_user)]):
    # Abrir o recargar el tablero cuenta como actividad.
    return _me_out(request, user)


@auth_router.post("/activity", status_code=status.HTTP_204_NO_CONTENT)
async def activity(user: Annotated[CurrentUser, Depends(active_user)]):
    """El tablero avisa que la persona lo está usando (clics, teclas, toques), a lo más una vez por minuto."""


@auth_router.put("/preferences", status_code=status.HTTP_204_NO_CONTENT)
async def save_preferences(body: PreferencesInput, session: Session, user: Annotated[CurrentUser, Depends(current_user)]):
    """Guarda el idioma del tablero en la cuenta, para que se respete en cualquier navegador o teléfono."""
    row = await session.get(db.User, user.id) if user.id else None
    if row is None:
        return  # inicio de sesión apagado: el tablero lo guarda solo en el navegador
    row.language = body.language
    await session.commit()


@auth_router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(body: PasswordChange, request: Request, session: Session,
                          user: Annotated[CurrentUser, Depends(current_user)]):
    row = await session.get(db.User, user.id) if user.id else None
    if row is None or not verify_password(body.current_password, row.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La contraseña actual no es correcta.")
    _check_password(request, body.new_password)
    row.password_hash = hash_password(body.new_password)
    # Cierra las demás sesiones abiertas con la contraseña anterior.
    token = request.cookies.get(request.app.state.settings.auth.cookie_name)
    await end_sessions(session, row.id, keep=token_hash(token) if token else None)
    audit.record(session, request, "auth.password_changed", user, entity_type="user", entity_id=row.id, entity_label=row.email)
    await session.commit()


# --- Cuentas (solo administradores) ---------------------------------------------------------------


def _actor(user: db.User | None) -> CurrentUser | None:
    return None if user is None else CurrentUser(user.id, user.email, user.name, Role(user.role))


async def _user_or_404(session: AsyncSession, user_id: uuid.UUID) -> db.User:
    user = await session.get(db.User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cuenta no encontrada")
    return user


async def _other_active_admins(session: AsyncSession, user_id: uuid.UUID) -> int:
    U = db.User
    return await session.scalar(
        select(func.count()).select_from(U).where(U.role == Role.ADMIN.value, U.active.is_(True), U.id != user_id)
    ) or 0


@users_router.get("", response_model=list[UserOut])
async def list_users(session: Session):
    return [UserOut.of(u) for u in (await session.scalars(select(db.User).order_by(db.User.name))).all()]


@users_router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def add_user(body: UserCreate, request: Request, session: Session, me: Admin):
    email = _check_email(body.email)
    _check_password(request, body.password)
    user = await create_user(session, email, body.name, body.role, body.password)
    audit.record(session, request, "user.created", me, entity_type="user", entity_id=user.id, entity_label=user.email,
                 changes=audit.diff({}, audit.user_snapshot(user)))
    try:
        await session.commit()
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya hay una cuenta con ese correo.") from None
    return UserOut.of(user)


@users_router.patch("/{user_id}", response_model=UserOut)
async def update_user(user_id: uuid.UUID, body: UserUpdate, request: Request, session: Session, me: Admin):
    user = await _user_or_404(session, user_id)
    before = audit.user_snapshot(user)
    losing_admin = (body.role is not None and body.role != Role.ADMIN) or body.active is False
    if losing_admin and user.role == Role.ADMIN.value and not await _other_active_admins(session, user.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Debe quedar al menos un administrador activo.")
    if body.name is not None:
        user.name = body.name.strip() or user.email
    if body.role is not None:
        user.role = body.role.value
    if body.active is not None:
        user.active = body.active
    if body.password:
        _check_password(request, body.password)
        user.password_hash = hash_password(body.password)
        user.failed_logins = 0
        user.locked_until = None
        await login_guard(request).unlock(user.email)
    if body.active is False or body.password:
        await end_sessions(session, user.id)  # el rol se lee en cada petición; esto cierra sus sesiones abiertas
    changes = audit.diff(before, audit.user_snapshot(user))
    if changes or body.password:
        # La contraseña nunca se guarda, ni cifrada: solo que se cambió.
        audit.record(session, request, "user.updated", me, entity_type="user", entity_id=user.id, entity_label=user.email,
                     changes=changes, detail={"passwordReset": True} if body.password else None)
    await session.commit()
    return UserOut.of(user)


@users_router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: uuid.UUID, request: Request, session: Session, me: Admin):
    user = await _user_or_404(session, user_id)
    if user.id == me.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "No puedes borrar tu propia cuenta.")
    if user.role == Role.ADMIN.value and not await _other_active_admins(session, user.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Debe quedar al menos un administrador activo.")
    await end_sessions(session, user.id)
    audit.record(session, request, "user.deleted", me, entity_type="user", entity_id=user.id, entity_label=user.email,
                 changes=audit.diff(audit.user_snapshot(user), {}))
    await session.delete(user)
    await session.commit()
