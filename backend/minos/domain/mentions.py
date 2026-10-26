"""Menciones: lo que entrega un conector, su análisis y la huella para detectar copias."""
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from .targets import normalize


class Sentiment(StrEnum):
    NEGATIVE = "Negative"
    NEUTRAL = "Neutral"
    POSITIVE = "Positive"


@dataclass(frozen=True)
class AuthorInfo:
    handle: str
    display_name: str | None = None
    followers: int = 0
    verified: bool = False


@dataclass(frozen=True)
class Engagement:
    likes: int = 0
    shares: int = 0
    replies: int = 0
    views: int = 0

    @property
    def interactions(self) -> int:
        return self.likes + self.shares + self.replies


@dataclass(frozen=True)
class MentionDraft:
    """Lo que entrega un conector, ya normalizado pero sin analizar."""

    source: str
    external_id: str
    url: str
    author: AuthorInfo
    published_at: datetime
    text: str
    language: str | None = None
    engagement: Engagement = field(default_factory=Engagement)
    # Comentario o publicación en un canal propio del objetivo (su página, su cuenta): habla de él aunque no lo nombre.
    own_channel: bool = False
    raw: dict | None = None


@dataclass(frozen=True)
class MentionAnalysis:
    """Resultado del análisis de texto de una mención."""

    sentiment: Sentiment
    score: float
    severe_accusation: bool = False
    topic: str | None = None
    summary: str | None = None
    analyzer: str = "lexicon"


_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_RETWEET = re.compile(r"^\s*RT\s+@\w+:?", re.IGNORECASE)


def fingerprint(text: str) -> str:
    """Huella del texto para detectar retuits, notas replicadas o el mismo texto con otra URL."""
    cleaned = _RETWEET.sub(" ", _URL.sub(" ", text))
    return hashlib.sha256(normalize(cleaned).strip().encode()).hexdigest()[:32]
