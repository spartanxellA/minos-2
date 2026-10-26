from collections.abc import AsyncIterator
from datetime import timedelta

import httpx

from ..config import BlueskySettings
from ..domain.mentions import AuthorInfo, Engagement, MentionDraft
from ..domain.targets import MonitoredTarget
from .base import ConnectorCursor, MentionConnector, parse_datetime, parse_since


class BlueskyConnector(MentionConnector):
    """Publicaciones de Bluesky vía app.bsky.feed.searchPosts, con la fecha de la última publicación como cursor."""

    source = "bluesky"

    def __init__(self, http: httpx.AsyncClient, settings: BlueskySettings) -> None:
        self._http = http
        self._settings = settings
        self._access_jwt: str | None = None

    @property
    def poll_interval(self) -> timedelta:
        return self._settings.poll_interval

    @property
    def is_configured(self) -> bool:
        return bool(self._settings.identifier and self._settings.app_password)

    async def _session(self) -> str:
        response = await self._http.post(
            f"{self._settings.service}/xrpc/com.atproto.server.createSession",
            json={"identifier": self._settings.identifier, "password": self._settings.app_password},
        )
        response.raise_for_status()
        return response.json()["accessJwt"]

    async def fetch(self, target: MonitoredTarget, cursor: ConnectorCursor) -> AsyncIterator[MentionDraft]:
        if self._access_jwt is None:
            self._access_jwt = await self._session()
        since = parse_since(cursor.value)
        newest = since
        # searchPosts no acepta OR con paréntesis; se busca cada nombre por separado.
        for name in target.search_names():
            response = await self._http.get(
                f"{self._settings.service}/xrpc/app.bsky.feed.searchPosts",
                params={
                    "sort": "latest",
                    "limit": 100,
                    "q": f'"{name}"' if " " in name else name,
                    "since": since.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
                },
                headers={"Authorization": f"Bearer {self._access_jwt}"},
            )
            if response.status_code == 401:
                self._access_jwt = None  # la próxima ronda abre sesión de nuevo
            response.raise_for_status()

            for post in response.json().get("posts", []):
                record = post.get("record") or {}
                created = parse_datetime(record.get("createdAt") or post["indexedAt"])
                if created <= since:
                    continue
                newest = max(newest, created)
                author = post["author"]
                rkey = post["uri"].rsplit("/", 1)[-1]
                yield MentionDraft(
                    source=self.source,
                    external_id=post["uri"],
                    url=f"https://bsky.app/profile/{author['handle']}/post/{rkey}",
                    author=AuthorInfo("@" + author["handle"], author.get("displayName")),
                    published_at=created,
                    text=record.get("text", ""),
                    language=(record.get("langs") or [None])[0],
                    engagement=Engagement(
                        likes=post.get("likeCount", 0),
                        shares=post.get("repostCount", 0) + post.get("quoteCount", 0),
                        replies=post.get("replyCount", 0),
                    ),
                )
        cursor.value = newest.isoformat()
