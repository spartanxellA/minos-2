import calendar
import html
import logging
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urlparse

import feedparser
import httpx

from ..config import RssSettings
from ..domain.mentions import AuthorInfo, GeoHint, MentionDraft
from ..domain.targets import MonitoredTarget
from .base import ConnectorCursor, MentionConnector, parse_since
from .query import build_query

log = logging.getLogger(__name__)
_TAG = re.compile(r"<.*?>", re.DOTALL)


def _strip_html(value: str) -> str:
    return " ".join(html.unescape(_TAG.sub(" ", value)).split())


def _published(entry) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime.fromtimestamp(calendar.timegm(parsed), UTC) if parsed else None


class RssConnector(MentionConnector):
    """Noticias web por RSS: Google Noticias por objetivo más feeds de medios configurados."""

    source = "rss"

    def __init__(self, http: httpx.AsyncClient, settings: RssSettings) -> None:
        self._http = http
        self._settings = settings

    @property
    def poll_interval(self) -> timedelta:
        return self._settings.poll_interval

    @property
    def is_configured(self) -> bool:
        return self._settings.use_google_news_search or bool(self._settings.feeds)

    def feed_urls(self, target: MonitoredTarget) -> list[str]:
        urls = []
        if self._settings.use_google_news_search:
            q = quote(build_query(target), safe="")
            urls.append(f"https://news.google.com/rss/search?q={q}&{self._settings.google_news_locale}")
        return urls + list(self._settings.feeds)

    async def fetch(self, target: MonitoredTarget, cursor: ConnectorCursor) -> AsyncIterator[MentionDraft]:
        since = parse_since(cursor.value)
        newest = since
        for url in self.feed_urls(target):
            try:
                response = await self._http.get(url, follow_redirects=True)
                response.raise_for_status()
            except httpx.HTTPError as ex:
                log.warning("No se pudo leer el feed %s: %s", url, ex)
                continue
            feed = feedparser.parse(response.content)
            outlet_default = feed.feed.get("title") or urlparse(url).hostname or "rss"
            for entry in feed.entries:
                published = _published(entry)
                if published is None or published <= since:
                    continue
                newest = max(newest, published)
                link = entry.get("link") or entry.get("id", "")
                source = entry.get("source") or {}
                outlet = source.get("title") or outlet_default
                summary = _strip_html(entry.get("summary", ""))
                yield MentionDraft(
                    source=self.source,
                    external_id=entry.get("id") or link,
                    url=link,
                    author=AuthorInfo(outlet, outlet),
                    published_at=published,
                    text=f"{entry.get('title', '')} {summary}".strip(),
                    # Google Noticias dice qué medio publicó la nota; en un feed propio, el medio es el feed.
                    geo=GeoHint(outlet_url=source.get("href") or url, outlet_name=outlet),
                )
        cursor.value = newest.isoformat()
