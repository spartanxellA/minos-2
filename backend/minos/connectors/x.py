import logging
from collections.abc import AsyncIterator
from datetime import timedelta

import httpx

from ..config import XSettings
from ..domain.mentions import AuthorInfo, Engagement, MentionDraft
from ..domain.targets import MonitoredTarget
from .base import ConnectorCursor, MentionConnector, parse_datetime
from .query import build_query

log = logging.getLogger(__name__)
SEARCH_URL = "https://api.x.com/2/tweets/search/recent"


class XConnector(MentionConnector):
    """X / Twitter vía búsqueda reciente de la API v2 oficial, con since_id como cursor."""

    source = "x"

    def __init__(self, http: httpx.AsyncClient, settings: XSettings) -> None:
        self._http = http
        self._settings = settings

    @property
    def poll_interval(self) -> timedelta:
        return self._settings.poll_interval

    @property
    def is_configured(self) -> bool:
        return bool(self._settings.bearer_token)

    async def fetch(self, target: MonitoredTarget, cursor: ConnectorCursor) -> AsyncIterator[MentionDraft]:
        query = build_query(target)
        if self._settings.exclude_retweets:
            query += " -is:retweet"
        params = {
            "query": query,
            "max_results": min(max(self._settings.max_results, 10), 100),
            "tweet.fields": "created_at,public_metrics,lang,author_id",
            "expansions": "author_id",
            "user.fields": "public_metrics,verified,username,name",
        }
        if cursor.value:
            params["since_id"] = cursor.value

        response = await self._http.get(
            SEARCH_URL, params=params, headers={"Authorization": f"Bearer {self._settings.bearer_token}"}
        )
        if response.is_error:
            log.warning("X respondió %s para %s", response.status_code, target.name)
            response.raise_for_status()

        page = response.json()
        users = {u["id"]: u for u in (page.get("includes") or {}).get("users", [])}
        for t in page.get("data") or []:
            user = users.get(t.get("author_id", ""))
            metrics = t.get("public_metrics") or {}
            if user:
                handle, url = "@" + user["username"], f"https://x.com/{user['username']}/status/{t['id']}"
            else:
                handle, url = t.get("author_id") or "?", f"https://x.com/i/web/status/{t['id']}"
            yield MentionDraft(
                source=self.source,
                external_id=t["id"],
                url=url,
                author=AuthorInfo(
                    handle,
                    user.get("name") if user else None,
                    ((user or {}).get("public_metrics") or {}).get("followers_count", 0),
                    bool((user or {}).get("verified")),
                ),
                published_at=parse_datetime(t["created_at"]),
                text=t["text"],
                language=t.get("lang"),
                engagement=Engagement(
                    likes=metrics.get("like_count", 0),
                    shares=metrics.get("retweet_count", 0) + metrics.get("quote_count", 0),
                    replies=metrics.get("reply_count", 0),
                    views=metrics.get("impression_count", 0),
                ),
                raw=t,
            )
        if newest := (page.get("meta") or {}).get("newest_id"):
            cursor.value = newest
