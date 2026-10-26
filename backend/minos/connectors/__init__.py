"""Conectores de fuentes (los "scrapers"). Cada uno solo trae y normaliza; el análisis es común."""
import httpx

from ..config import Settings
from .base import USER_AGENT, ConnectorCursor, ConnectorMode, MentionConnector, redact_secrets
from .bluesky import BlueskyConnector
from .demo import DemoConnector
from .meta import FacebookPageConnector, InstagramConnector
from .reddit import RedditConnector
from .rss import RssConnector
from .x import XConnector
from .youtube import YouTubeConnector

__all__ = [
    "ConnectorCursor", "ConnectorMode", "MentionConnector", "build_connectors", "new_http_client", "redact_secrets",
    "BlueskyConnector", "DemoConnector", "FacebookPageConnector", "InstagramConnector", "RedditConnector",
    "RssConnector", "XConnector", "YouTubeConnector",
]


def new_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=httpx.Timeout(30.0))


def build_connectors(settings: Settings, http: httpx.AsyncClient) -> list[MentionConnector]:
    """Conectores por consulta, más el de demostración si está activado. Bluesky en vivo (Jetstream) va aparte."""
    c = settings.connectors
    return [
        RssConnector(http, c.rss),
        XConnector(http, c.x),
        YouTubeConnector(http, c.youtube),
        BlueskyConnector(http, c.bluesky),
        RedditConnector(http, c.reddit),
        FacebookPageConnector(http, c.meta),
        InstagramConnector(http, c.meta),
        DemoConnector(settings.demo),
    ]
