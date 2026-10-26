"""Bluesky en tiempo real con Jetstream: todas las publicaciones nuevas de la red, sin cuenta ni cuota.

Jetstream solo trae el DID del autor; la cuenta y los seguidores se piden al AppView público, y solo para las
publicaciones que coinciden con algún objetivo."""
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlencode

import httpx

from ..config import JetstreamSettings
from ..domain.mentions import AuthorInfo, MentionDraft
from .base import parse_datetime

POST_COLLECTION = "app.bsky.feed.post"


@dataclass(frozen=True)
class StreamPost:
    did: str
    rkey: str
    text: str
    created_at: datetime
    language: str | None

    @property
    def uri(self) -> str:
        # El mismo id externo que usa el conector de búsqueda: así no se duplica si ambos están activos.
        return f"at://{self.did}/{POST_COLLECTION}/{self.rkey}"


def subscribe_url(settings: JetstreamSettings, cursor_us: int | None) -> str:
    params: dict = {"wantedCollections": POST_COLLECTION}
    if cursor_us:
        params["cursor"] = cursor_us
    return f"{settings.url}?{urlencode(params)}"


def parse_event(event: dict) -> StreamPost | None:
    """Publicación nueva, o None para todo lo demás (borrados, ediciones, cambios de cuenta)."""
    commit = event.get("commit") or {}
    if event.get("kind") != "commit" or commit.get("operation") != "create" or commit.get("collection") != POST_COLLECTION:
        return None
    record = commit.get("record") or {}
    text = record.get("text") or ""
    if not text.strip():
        return None
    try:
        created = parse_datetime(record["createdAt"])
    except (KeyError, ValueError):
        return None
    return StreamPost(event["did"], commit["rkey"], text, created, (record.get("langs") or [None])[0])


class ProfileDirectory:
    """Cuenta, nombre y seguidores por DID, con caché (las mismas cuentas publican seguido)."""

    MAX_CACHE = 20_000

    def __init__(self, http: httpx.AsyncClient, settings: JetstreamSettings) -> None:
        self._http = http
        self._settings = settings
        self._cache: dict[str, AuthorInfo] = {}

    async def resolve(self, dids: set[str]) -> dict[str, AuthorInfo]:
        missing = [d for d in dids if d not in self._cache]
        for i in range(0, len(missing), 25):  # getProfiles acepta hasta 25
            batch = missing[i:i + 25]
            try:
                response = await self._http.get(
                    f"{self._settings.profile_api}/xrpc/app.bsky.actor.getProfiles", params=[("actors", d) for d in batch]
                )
                response.raise_for_status()
                profiles = response.json().get("profiles", [])
            except httpx.HTTPError:
                profiles = []  # sin perfil la mención se guarda igual, con el DID como autor
            if len(self._cache) > self.MAX_CACHE:
                self._cache.clear()
            for p in profiles:
                self._cache[p["did"]] = AuthorInfo("@" + p["handle"], p.get("displayName"), p.get("followersCount", 0))
        return {d: self._cache.get(d, AuthorInfo(d)) for d in dids}

    @staticmethod
    def draft(post: StreamPost, author: AuthorInfo) -> MentionDraft:
        profile = author.handle.removeprefix("@") if author.handle.startswith("@") else post.did
        return MentionDraft(
            source="bluesky",
            external_id=post.uri,
            url=f"https://bsky.app/profile/{profile}/post/{post.rkey}",
            author=author,
            published_at=post.created_at,
            text=post.text,
            language=post.language,
        )
