"""Conectores contra respuestas grabadas (httpx.MockTransport), sin salir a internet."""
import json
from datetime import UTC, datetime, timedelta

import httpx
from minos.config import BlueskySettings, RssSettings, XSettings, YouTubeSettings
from minos.connectors import (
    BlueskyConnector,
    ConnectorCursor,
    RssConnector,
    XConnector,
    YouTubeConnector,
)
from minos.connectors.base import Backoff, SourceUnavailable, retry_after
from minos.domain.targets import MonitoredTarget

TARGET = MonitoredTarget(name="Ana López")


def stub(handler):
    requests = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    return httpx.AsyncClient(transport=httpx.MockTransport(record)), requests


async def collect(connector, cursor):
    return [d async for d in connector.fetch(TARGET, cursor)]


X_PAYLOAD = {
    "data": [{
        "id": "1850", "text": "Critican a Ana López por el presupuesto", "author_id": "u1",
        "created_at": "2026-10-25T18:00:00.000Z", "lang": "es",
        "public_metrics": {"retweet_count": 4, "reply_count": 2, "like_count": 10, "quote_count": 1, "impression_count": 900},
    }],
    "includes": {"users": [{"id": "u1", "name": "Diario", "username": "diario", "verified": True,
                            "public_metrics": {"followers_count": 120000}}]},
    "meta": {"newest_id": "1850", "result_count": 1},
}


async def test_x_maps_tweets_authors_metrics_and_advances_cursor():
    http, requests = stub(lambda r: httpx.Response(200, json=X_PAYLOAD))
    connector = XConnector(http, XSettings(bearer_token="t"))
    cursor = ConnectorCursor("1700")

    [m] = await collect(connector, cursor)

    assert m.author.handle == "@diario"
    assert m.author.followers == 120000
    assert m.engagement.likes == 10
    assert m.engagement.shares == 5
    assert m.url == "https://x.com/diario/status/1850"
    assert cursor.value == "1850"
    url = str(requests[0].url)
    assert "since_id=1700" in url
    assert "-is%3Aretweet" in url
    assert requests[0].headers["authorization"] == "Bearer t"


def test_x_without_token_is_off():
    assert not XConnector(httpx.AsyncClient(), XSettings()).is_configured


FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Google Noticias</title><link>https://news.google.com</link><description>d</description>
  <item><title>Ana López anuncia programa - El Diario</title><link>https://example.com/a</link><guid>a1</guid>
    <pubDate>Sun, 25 Oct 2026 17:00:00 GMT</pubDate><description>&lt;a href="x"&gt;Ana López&lt;/a&gt; anunció</description></item>
  <item><title>Nota vieja</title><link>https://example.com/b</link><guid>b1</guid><pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate></item>
</channel></rss>"""


async def test_rss_reads_only_items_newer_than_cursor_and_strips_html():
    http, requests = stub(lambda r: httpx.Response(200, text=FEED, headers={"content-type": "application/rss+xml"}))
    connector = RssConnector(http, RssSettings())
    cursor = ConnectorCursor("2026-10-01T00:00:00Z")

    [m] = await collect(connector, cursor)

    assert m.url == "https://example.com/a"
    assert "<a" not in m.text
    assert cursor.value.startswith("2026-10-25T17:00:00")
    assert "news.google.com/rss/search" in str(requests[0].url)


async def test_rss_feed_error_is_skipped_not_fatal():
    http, _ = stub(lambda r: httpx.Response(503))
    connector = RssConnector(http, RssSettings())
    assert await collect(connector, ConnectorCursor()) == []


async def test_youtube_maps_videos_and_uses_published_after():
    payload = {"items": [{
        "id": {"videoId": "abc"},
        "snippet": {"publishedAt": "2026-10-25T12:00:00Z", "channelId": "c1", "channelTitle": "Canal",
                    "title": "Ana López en entrevista", "description": "Habla de su gestión"},
    }]}
    http, requests = stub(lambda r: httpx.Response(200, json=payload))
    cursor = ConnectorCursor("2026-10-20T00:00:00+00:00")

    [m] = await collect(YouTubeConnector(http, YouTubeSettings(api_key="k")), cursor)

    assert m.url == "https://www.youtube.com/watch?v=abc"
    assert m.author.handle == "Canal"
    assert "publishedAfter=2026-10-20T00%3A00%3A00Z" in str(requests[0].url)
    assert cursor.value.startswith("2026-10-25T12:00:00")


async def test_bluesky_opens_session_and_maps_posts():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("createSession"):
            assert json.loads(request.content)["identifier"] == "minos.bsky.social"
            return httpx.Response(200, json={"accessJwt": "jwt"})
        assert request.headers["authorization"] == "Bearer jwt"
        return httpx.Response(200, json={"posts": [{
            "uri": "at://did:plc:x/app.bsky.feed.post/3k", "indexedAt": "2026-10-25T10:00:01Z",
            "author": {"handle": "reportera.bsky.social", "displayName": "Reportera"},
            "record": {"text": "Ana López no respondió", "createdAt": "2026-10-25T10:00:00Z", "langs": ["es"]},
            "likeCount": 3, "repostCount": 2, "quoteCount": 1, "replyCount": 4,
        }]})

    http, _ = stub(handler)
    connector = BlueskyConnector(http, BlueskySettings(identifier="minos.bsky.social", app_password="p"))
    cursor = ConnectorCursor("2026-10-24T00:00:00+00:00")

    [m] = await collect(connector, cursor)

    assert m.url == "https://bsky.app/profile/reportera.bsky.social/post/3k"
    assert m.engagement.shares == 3
    assert m.language == "es"
    assert cursor.value.startswith("2026-10-25T10:00:00")


# --- Pausas y reintentos ante 429/402/403 ---------------------------------------------------------------

TARGET_B = MonitoredTarget(name="Beto Ruiz")


def test_retry_after_reads_seconds_http_date_and_x_reset():
    now = datetime(2026, 11, 2, 23, 0, tzinfo=UTC)
    assert retry_after(httpx.Response(429, headers={"Retry-After": "120"}), now) == timedelta(seconds=120)
    assert retry_after(httpx.Response(429, headers={"Retry-After": "Mon, 02 Nov 2026 23:10:00 GMT"}), now) == timedelta(minutes=10)
    reset = str(int((now + timedelta(minutes=7)).timestamp()))
    assert retry_after(httpx.Response(429, headers={"x-rate-limit-reset": reset}), now) == timedelta(minutes=7)
    assert retry_after(httpx.Response(429), now) is None


def test_backoff_doubles_until_cap_and_clears_on_success():
    b, now = Backoff(), datetime(2026, 11, 2, tzinfo=UTC)
    assert b.pause("k", httpx.Response(429), now) == now + timedelta(minutes=15)
    assert b.pause("k", httpx.Response(429), now) == now + timedelta(minutes=30)
    assert b.paused_until("k", now) is not None
    b.ok("k")
    assert b.paused_until("k", now) is None
    assert b.pause("k", httpx.Response(500), now) is None


async def test_rss_shared_feed_is_downloaded_once_for_all_targets_with_browser_headers():
    http, requests = stub(lambda r: httpx.Response(200, text=FEED))
    connector = RssConnector(http, RssSettings(use_google_news_search=False, feeds=["https://medio.mx/rss"],
                                               min_gap_per_host=0))
    await collect(connector, ConnectorCursor("2026-10-01T00:00:00+00:00"))
    [d async for d in connector.fetch(TARGET_B, ConnectorCursor("2026-10-01T00:00:00+00:00"))]

    assert len(requests) == 1
    assert requests[0].headers["user-agent"].startswith("Mozilla/5.0")
    assert "rss" in requests[0].headers["accept"]


async def test_rss_402_pauses_the_feed_and_reports_what_to_do():
    http, requests = stub(lambda r: httpx.Response(402))
    connector = RssConnector(http, RssSettings(use_google_news_search=False, feeds=["https://rss.app/feeds/abc.xml"],
                                               min_gap_per_host=0))
    first = ConnectorCursor()
    assert await collect(connector, first) == []
    [note] = first.warnings
    assert note.startswith("rss.app/feeds/abc.xml: 402, la fuente pide pago")
    assert "En pausa hasta" in note and note.endswith("renueva el plan del servicio o quita el feed de RSS_FEEDS")

    second = ConnectorCursor()
    await collect(connector, second)
    assert len(requests) == 1  # en pausa: ya no se vuelve a pedir
    assert second.warnings == [note]  # mismo motivo y consejo, así «Fuentes» lo agrupa en un solo aviso


async def test_rss_429_pauses_the_whole_site_respecting_retry_after():
    http, requests = stub(lambda r: httpx.Response(429, headers={"Retry-After": "600"}))
    feeds = ["https://www.eluniversal.com.mx/a/rss.xml", "https://www.eluniversal.com.mx/b/rss.xml"]
    connector = RssConnector(http, RssSettings(use_google_news_search=False, feeds=feeds, min_gap_per_host=0))
    cursor = ConnectorCursor()
    await collect(connector, cursor)
    assert len(requests) == 1  # el segundo feed del mismo sitio no se pide
    assert cursor.warnings[1].startswith("eluniversal.com.mx/b/rss.xml: 429, demasiadas consultas")
    assert "Todo el sitio en pausa hasta" in cursor.warnings[1]


async def test_x_402_pauses_connector_for_every_target():
    http, _ = stub(lambda r: httpx.Response(402, json={"title": "Payment Required"}))
    connector = XConnector(http, XSettings(bearer_token="t"))
    try:
        await collect(connector, ConnectorCursor())
        raise AssertionError("debió fallar")
    except SourceUnavailable as ex:
        assert "créditos" in str(ex)
    assert connector.paused_until is not None


async def test_youtube_quota_exceeded_pauses_until_pacific_midnight():
    body = {"error": {"code": 403, "errors": [{"reason": "quotaExceeded"}]}}
    http, _ = stub(lambda r: httpx.Response(403, json=body))
    connector = YouTubeConnector(http, YouTubeSettings(api_key="k"))
    try:
        await collect(connector, ConnectorCursor())
        raise AssertionError("debió fallar")
    except SourceUnavailable as ex:
        assert "cuota" in str(ex)
    until = connector.paused_until
    assert until is not None and timedelta(0) < until - datetime.now(UTC) <= timedelta(hours=25)


def test_youtube_spreads_daily_quota_across_targets():
    connector = YouTubeConnector(httpx.AsyncClient(), YouTubeSettings(api_key="k"))
    connector.plan_round(1)
    assert connector.poll_interval == timedelta(minutes=30)
    connector.plan_round(10)  # 10 × 101 unidades × n consultas ≤ 9,000 al día
    assert connector.poll_interval > timedelta(hours=2)
    assert 10 * 101 * (timedelta(days=1) / connector.poll_interval) <= 9_000 + 1
