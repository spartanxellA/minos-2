import asyncio
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
from .base import (
    PAUSE_HINTS,
    Backoff,
    ConnectorCursor,
    MentionConnector,
    local_time,
    parse_since,
)
from .query import build_query

log = logging.getLogger(__name__)
_TAG = re.compile(r"<.*?>", re.DOTALL)

# Qué hacer según la respuesta de un feed propio (RSS_FEEDS en .env).
_FEED_ADVICE = {
    402: "renueva el plan del servicio o quita el feed de RSS_FEEDS",
    403: "el sitio bloquea lectores automáticos; si sigue igual, quita el feed de RSS_FEEDS",
    401: "el feed pide usuario y contraseña; quítalo de RSS_FEEDS",
    404: "revisa la dirección en RSS_FEEDS",
    410: "quita el feed de RSS_FEEDS",
}


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
        self._backoff = Backoff()
        # Los feeds de medios son los mismos para todos los objetivos: se descargan una vez por intervalo y cada
        # objetivo filtra lo suyo. Antes cada objetivo los pedía por su cuenta y los sitios respondían 429.
        self._cache: dict[str, tuple[datetime, bytes]] = {}
        self._validators: dict[str, dict[str, str]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_hit: dict[str, float] = {}
        self._headers = {
            "User-Agent": settings.user_agent,
            "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5",
            "Accept-Language": "es-MX,es;q=0.9,en;q=0.5",
        }

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
        shared = set(self._settings.feeds)
        for url in self.feed_urls(target):
            content = await self._read(url, cursor, shared=url in shared)
            if content is None:
                continue
            feed = feedparser.parse(content)
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

    async def _read(self, url: str, cursor: ConnectorCursor, shared: bool) -> bytes | None:
        """Contenido del feed, desde la copia reciente si es un feed compartido, o None si no se pudo leer."""
        host = urlparse(url).hostname or url
        lock = self._locks.setdefault(url, asyncio.Lock())
        async with lock:
            now = datetime.now(UTC)
            if shared and (cached := self._cache.get(url)) and now - cached[0] < self._settings.poll_interval:
                return cached[1]
            # Un 429 suele valer para todo el sitio; un 402/403/404 solo para ese feed.
            for key in (host, url):
                if until := self._backoff.paused_until(key, now):
                    cursor.warnings.append(self._pause_note(url, key, until))
                    return None
            await self._space(host)
            headers = dict(self._headers)
            if shared:
                headers.update(self._validators.get(url, {}))
            try:
                response = await self._http.get(url, headers=headers, follow_redirects=True)
            except httpx.HTTPError as ex:
                log.warning("No se pudo leer el feed %s: %s", url, type(ex).__name__)
                cursor.warnings.append(f"{_label(url)}: sin respuesta ({type(ex).__name__})")
                return None
            if response.status_code == 304 and url in self._cache:
                self._cache[url] = (now, self._cache[url][1])
                return self._cache[url][1]
            if response.is_error:
                self._fail(url, host, response, cursor)
                return None
            self._backoff.ok(host)
            self._backoff.ok(url)
            if shared:
                self._cache[url] = (now, response.content)
                self._validators[url] = {
                    h: v for h, v in (("If-None-Match", response.headers.get("etag")),
                                      ("If-Modified-Since", response.headers.get("last-modified"))) if v
                }
            return response.content

    async def _space(self, host: str) -> None:
        """Deja un respiro entre consultas seguidas al mismo sitio (Google Noticias recibe una por objetivo)."""
        gap = self._settings.min_gap_per_host.total_seconds()
        loop = asyncio.get_running_loop()
        if gap > 0 and (last := self._last_hit.get(host)) is not None and (wait := last + gap - loop.time()) > 0:
            await asyncio.sleep(wait)
        self._last_hit[host] = loop.time()

    def _fail(self, url: str, host: str, response: httpx.Response, cursor: ConnectorCursor) -> None:
        code = response.status_code
        key = host if code in (429, 503) else url
        until = self._backoff.pause(key, response)
        if until is None:
            log.warning("No se pudo leer el feed %s: %s", url, code)
            cursor.warnings.append(f"{_label(url)}: respondió {code}")
            return
        advice = _FEED_ADVICE.get(code) if url in self._settings.feeds else None
        note = f"{_label(url)}: {code}, {PAUSE_HINTS[code]}. En pausa hasta {local_time(until)}"
        if advice:
            note += f"; {advice}"
        log.warning("Feed %s: %s", url, note)
        cursor.warnings.append(note)

    def _pause_note(self, url: str, key: str, until: datetime) -> str:
        scope = "el sitio" if key != url else "el feed"
        return f"{_label(url)}: {scope} sigue en pausa hasta {local_time(until)}"


def _label(url: str) -> str:
    """Nombre corto del feed para los avisos (sin la consulta de Google Noticias, que repite el objetivo)."""
    parsed = urlparse(url)
    if parsed.hostname == "news.google.com":
        return "Google Noticias"
    return (parsed.hostname or url).removeprefix("www.") + (parsed.path if parsed.path not in ("", "/") else "")
