import logging
from collections.abc import AsyncIterator
from datetime import timedelta

import httpx

from ..config import YouTubeSettings
from ..domain.mentions import AuthorInfo, GeoHint, MentionDraft
from ..domain.targets import MonitoredTarget
from .base import ConnectorCursor, MentionConnector, parse_datetime, parse_since
from .query import build_query

log = logging.getLogger(__name__)
SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"


class YouTubeConnector(MentionConnector):
    """Videos nuevos que mencionan al objetivo (título y descripción), vía YouTube Data API v3."""

    source = "youtube"

    def __init__(self, http: httpx.AsyncClient, settings: YouTubeSettings) -> None:
        self._http = http
        self._settings = settings

    @property
    def poll_interval(self) -> timedelta:
        return self._settings.poll_interval

    @property
    def is_configured(self) -> bool:
        return bool(self._settings.api_key)

    async def fetch(self, target: MonitoredTarget, cursor: ConnectorCursor) -> AsyncIterator[MentionDraft]:
        since = parse_since(cursor.value)
        response = await self._http.get(SEARCH_URL, params={
            "part": "snippet",
            "type": "video",
            "order": "date",
            "maxResults": 50,
            "q": build_query(target, or_operator="|"),
            "publishedAfter": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "regionCode": self._settings.region_code,
            "relevanceLanguage": self._settings.relevance_language,
            "key": self._settings.api_key,
        })
        response.raise_for_status()
        items = response.json().get("items", [])
        countries = await self._channel_countries({(i.get("snippet") or {}).get("channelId") for i in items} - {None})
        newest = since
        for item in items:
            video_id = (item.get("id") or {}).get("videoId")
            s = item.get("snippet")
            if not video_id or not s:
                continue
            published = parse_datetime(s["publishedAt"])
            newest = max(newest, published)
            channel = s.get("channelTitle") or s.get("channelId") or "?"
            yield MentionDraft(
                source=self.source,
                external_id=video_id,
                url=f"https://www.youtube.com/watch?v={video_id}",
                author=AuthorInfo(channel, s.get("channelTitle")),
                published_at=published,
                text=f"{s.get('title', '')} {s.get('description', '')}".strip(),
                geo=GeoHint(country_code=countries[s["channelId"]]) if s.get("channelId") in countries else None,
            )
        cursor.value = newest.isoformat()

    async def _channel_countries(self, channel_ids: set[str]) -> dict[str, str]:
        """País declarado de cada canal (channels.list cuesta 1 unidad por cada 50). Si falla, se sigue sin él."""
        countries: dict[str, str] = {}
        ids = sorted(channel_ids)
        for start in range(0, len(ids), 50):
            try:
                response = await self._http.get(CHANNELS_URL, params={
                    "part": "snippet", "id": ",".join(ids[start:start + 50]), "maxResults": 50, "key": self._settings.api_key,
                })
                response.raise_for_status()
            except httpx.HTTPError as ex:
                log.warning("No se pudo leer el país de los canales de YouTube: %s", type(ex).__name__)
                return countries
            for channel in response.json().get("items", []):
                if isinstance(channel.get("id"), str) and (country := (channel.get("snippet") or {}).get("country")):
                    countries[channel["id"]] = country
        return countries
