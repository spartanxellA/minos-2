"""Rutas de inicio de sesión (/api/auth) y de administración de cuentas (/api/users)."""
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from . import db
from .auth import (
    _DUMMY_HASH, ROLE_LABEL, CurrentUser, Role, create_user, current_user, end_sessions, hash_password,
    new_session_token, normalize_email, require_role, token_hash, verify_password,
)
from .schemas import Camel


async def get_session(request: Request):
    async with request.app.state.db.session() as session:
        yield session


Session = Annotated[AsyncSession, Depends(get_session)]
auth_router = APIRouter(prefix="/api/auth")
users_router = APIRouter(prefix="/api/users", dependencies=[Depends(require_role(Role.ADMIN))])


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
    user = await session.scalar(select(db.User).where(db.User.email == normalize_email(body.email)))
    if user is not None and user.locked_until and user.locked_until > now:
        minutes = max(int((user.locked_until - now).total_seconds() // 60) + 1, 1)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"Demasiados intentos. Vuelve a intentar en {minutes} min.")
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if user is None or not ok or not user.active:
        if user is not None and not ok:
            user.failed_logins += 1
            if user.failed_logins >= a.max_failed_logins:
                user.locked_until = now + a.lockout
                user.failed_logins = 0
            await session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Correo o contraseña incorrectos.")

    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    token = new_session_token()
    session.add(db.UserSession(token_hash=token_hash(token), user_id=user.id, created_at=now, expires_at=now + a.session_ttl))
    await session.execute(delete(db.UserSession).where(db.UserSession.expires_at <= now))
    await session.commit()
    response.set_cookie(
        a.cookie_name, token, max_age=int(a.session_ttl.total_seconds()), httponly=True, samesite="lax",
        secure=not settings.is_development, path="/",
    )
    return MeOut(**UserOut.of(user).model_dump(), auth_mode=a.mode)


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, session: Session):
    a = request.app.state.settings.auth
    token = request.cookies.get(a.cookie_name)
    if token:
        await session.execute(delete(db.UserSession).where(db.UserSession.token_hash == token_hash(token)))
        await session.commit()
    response.delete_cookie(a.cookie_name, path="/")


@auth_router.get("/me", response_model=MeOut)
async def me(request: Request, user: Annotated[CurrentUser, Depends(current_user)]):
    return MeOut(**UserOut.of(user).model_dump(), auth_mode=request.app.state.settings.auth.mode)


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
    await session.commit()


# --- Cuentas (solo administradores) ---------------------------------------------------------------


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
async def add_user(body: UserCreate, request: Request, session: Session):
    email = _check_email(body.email)
    _check_password(request, body.password)
    user = await create_user(session, email, body.name, body.role, body.password)
    try:
        await session.commit()
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya hay una cuenta con ese correo.") from None
    return UserOut.of(user)


@users_router.patch("/{user_id}", response_model=UserOut)
async def update_user(user_id: uuid.UUID, body: UserUpdate, request: Request, session: Session):
    user = await _user_or_404(session, user_id)
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
    if body.active is False or body.password:
        await end_sessions(session, user.id)  # el rol se lee en cada petición; esto cierra sus sesiones abiertas
    await session.commit()
    return UserOut.of(user)


@users_router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: uuid.UUID, session: Session, me: Annotated[CurrentUser, Depends(current_user)]):
    user = await _user_or_404(session, user_id)
    if user.id == me.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "No puedes borrar tu propia cuenta.")
    if user.role == Role.ADMIN.value and not await _other_active_admins(session, user.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Debe quedar al menos un administrador activo.")
    await end_sessions(session, user.id)
    await session.delete(user)
    await session.commit()
