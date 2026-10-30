import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx

from ..config import RedditSettings
from ..domain.mentions import AuthorInfo, Engagement, GeoHint, MentionDraft
from ..domain.targets import MonitoredTarget
from .base import ConnectorCursor, MentionConnector, parse_since
from .query import build_query

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_URL = "https://oauth.reddit.com"


class RedditConnector(MentionConnector):
    """Publicaciones de Reddit vía la API oficial (OAuth de aplicación), con la fecha de la última como cursor.

    La API no permite buscar comentarios; los homónimos se filtran después con is_relevant."""

    source = "reddit"

    def __init__(self, http: httpx.AsyncClient, settings: RedditSettings) -> None:
        self._http = http
        self._settings = settings
        self._token: str | None = None
        self._token_expires = 0.0

    @property
    def poll_interval(self) -> timedelta:
        return self._settings.poll_interval

    @property
    def is_configured(self) -> bool:
        return bool(self._settings.client_id and self._settings.client_secret)

    async def _access_token(self) -> str:
        if self._token is None or time.monotonic() >= self._token_expires:
            response = await self._http.post(
                TOKEN_URL, data={"grant_type": "client_credentials"},
                auth=(self._settings.client_id, self._settings.client_secret),
                headers={"User-Agent": self._settings.user_agent},
            )
            response.raise_for_status()
            body = response.json()
            self._token = body["access_token"]
            self._token_expires = time.monotonic() + max(int(body.get("expires_in", 3600)) - 60, 60)
        return self._token

    async def fetch(self, target: MonitoredTarget, cursor: ConnectorCursor) -> AsyncIterator[MentionDraft]:
        since = parse_since(cursor.value)
        newest = since
        subreddits = "+".join(self._settings.subreddits)
        url = f"{API_URL}/r/{subreddits}/search" if subreddits else f"{API_URL}/search"
        params = {
            "q": build_query(target, include_exclusions=False), "sort": "new", "t": "week", "limit": 100,
            "type": "link", "raw_json": 1,
        }
        if subreddits:
            params["restrict_sr"] = 1
        response = await self._http.get(url, params=params, headers={
            "Authorization": f"Bearer {await self._access_token()}", "User-Agent": self._settings.user_agent,
        })
        if response.status_code == 401:
            self._token = None  # la próxima ronda pide otro token
        response.raise_for_status()

        for child in response.json().get("data", {}).get("children", []):
            post = child.get("data") or {}
            created = datetime.fromtimestamp(post.get("created_utc", 0), UTC)
            if created <= since:
                continue
            newest = max(newest, created)
            text = post.get("title", "")
            if post.get("selftext"):
                text += "\n\n" + post["selftext"]
            yield MentionDraft(
                source=self.source,
                external_id=post["name"],
                url="https://www.reddit.com" + post.get("permalink", ""),
                author=AuthorInfo("u/" + post.get("author", "[deleted]"), post.get("subreddit_name_prefixed")),
                published_at=created,
                text=text,
                engagement=Engagement(
                    likes=max(post.get("score", 0), 0),
                    shares=post.get("num_crossposts", 0),
                    replies=post.get("num_comments", 0),
                ),
                # r/mexico, r/Monterrey, r/guadalajara: la comunidad dice de dónde se habla.
                geo=GeoHint(community=post.get("subreddit")) if post.get("subreddit") else None,
            )
        cursor.value = newest.isoformat()
