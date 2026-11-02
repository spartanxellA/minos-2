import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx

from ..config import YouTubeSettings
from ..domain.mentions import AuthorInfo, GeoHint, MentionDraft
from ..domain.targets import MonitoredTarget
from .base import (
    PAUSE_HINTS,
    Backoff,
    ConnectorCursor,
    MentionConnector,
    SourceUnavailable,
    local_time,
    parse_datetime,
    parse_since,
)
from .query import build_query

log = logging.getLogger(__name__)
SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
SEARCH_COST = 100 + 1  # search.list + channels.list para el país de los canales
_QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded", "userRateLimitExceeded"}
_PACIFIC = ZoneInfo("America/Los_Angeles")  # la cuota diaria de Google se reinicia a medianoche del Pacífico


def next_quota_reset(now: datetime) -> datetime:
    local = now.astimezone(_PACIFIC)
    return datetime.combine(local.date() + timedelta(days=1), time(0, 5), _PACIFIC).astimezone(UTC)


def _error_reasons(response: httpx.Response) -> set[str]:
    try:
        error = response.json().get("error") or {}
    except ValueError:
        return set()
    return {e.get("reason") for e in error.get("errors") or [] if isinstance(e, dict)} - {None}


class YouTubeConnector(MentionConnector):
    """Videos nuevos que mencionan al objetivo (título y descripción), vía YouTube Data API v3."""

    source = "youtube"

    def __init__(self, http: httpx.AsyncClient, settings: YouTubeSettings) -> None:
        self._http = http
        self._settings = settings
        self._backoff = Backoff()
        self._interval = settings.poll_interval

    @property
    def poll_interval(self) -> timedelta:
        return self._interval

    @property
    def paused_until(self) -> datetime | None:
        return self._backoff.paused_until(self.source)

    def plan_round(self, active_targets: int) -> None:
        """Reparte la cuota diaria entre los objetivos: cada búsqueda cuesta ~101 unidades de 10,000 al día.

        Con 30 min fijos alcanzaba para dos objetivos; con más, la cuota se agotaba a media mañana (429/403).
        """
        budget = self._settings.daily_quota * self._settings.quota_share
        if active_targets <= 0 or budget <= 0:
            self._interval = self._settings.poll_interval
            return
        needed = timedelta(days=1) * active_targets * SEARCH_COST / budget
        interval = max(self._settings.poll_interval, needed)
        if interval != self._interval:
            log.info("YouTube: %s objetivos con cuota de %s unidades → cada objetivo se consulta cada %s min",
                     active_targets, self._settings.daily_quota, round(interval.total_seconds() / 60))
        self._interval = interval

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
        if response.is_error:
            self._fail(response)
        self._backoff.ok(self.source)
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

    def _fail(self, response: httpx.Response) -> None:
        code = response.status_code
        reasons = _error_reasons(response)
        if code in (403, 429) and reasons & _QUOTA_REASONS:
            until = self._backoff.pause_until(self.source, next_quota_reset(datetime.now(UTC)))
            message = (f"YouTube respondió {code}: se agotó la cuota diaria de la API ({', '.join(sorted(reasons))}). "
                       f"YouTube queda en pausa hasta {local_time(until)}, cuando Google reinicia la cuota. "
                       "Con muchos objetivos conviene pedir más cuota en Google Cloud o subir YOUTUBE_POLL_INTERVAL.")
        elif until := self._backoff.pause(self.source, response):
            detail = f" ({', '.join(sorted(reasons))})" if reasons else ""
            message = (f"YouTube respondió {code}{detail}: {PAUSE_HINTS[code]}. "
                       f"YouTube queda en pausa hasta {local_time(until)}; revisa YOUTUBE_API_KEY.")
        else:
            response.raise_for_status()
            return
        log.warning(message)
        raise SourceUnavailable(message)

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
