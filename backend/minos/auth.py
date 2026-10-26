"""Autenticación OIDC (Keycloak, Entra ID, Auth0...): valida el JWT del encabezado Authorization.

Sin MINOS_AUTH__AUTHORITY solo se permite correr en development.
"""
import asyncio
import logging
from functools import cached_property

import httpx
import jwt
from fastapi import HTTPException, Request, WebSocket, status

from .config import AuthSettings

log = logging.getLogger(__name__)


class TokenValidator:
    def __init__(self, settings: AuthSettings) -> None:
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self._settings.authority)

    @cached_property
    def _jwks(self) -> jwt.PyJWKClient:
        issuer = self._settings.authority.rstrip("/")
        config = httpx.get(f"{issuer}/.well-known/openid-configuration", timeout=10).raise_for_status().json()
        return jwt.PyJWKClient(config["jwks_uri"], cache_keys=True)

    async def validate(self, token: str) -> dict:
        try:
            key = await asyncio.to_thread(self._jwks.get_signing_key_from_jwt, token)
            return jwt.decode(
                token, key.key, algorithms=["RS256", "ES256", "PS256"], audience=self._settings.audience,
                issuer=self._settings.authority.rstrip("/"), options={"verify_aud": bool(self._settings.audience)},
            )
        except (jwt.PyJWTError, httpx.HTTPError) as ex:
            log.info("Token rechazado: %s", ex)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido", {"WWW-Authenticate": "Bearer"}) from ex


async def require_user(request: Request) -> dict | None:
    validator: TokenValidator = request.app.state.auth
    if not validator.enabled:
        return None
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falta el token", {"WWW-Authenticate": "Bearer"})
    return await validator.validate(header[7:])


async def websocket_user(ws: WebSocket) -> dict | None:
    """Los navegadores no mandan encabezados en WebSocket: el token llega en ?access_token=."""
    validator: TokenValidator = ws.app.state.auth
    if not validator.enabled:
        return None
    token = ws.query_params.get("access_token", "")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falta el token")
    return await validator.validate(token)
