"""Contratos JSON de la API, en camelCase para el tablero."""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from . import db
from .connectors.base import redact_secrets
from .domain.risk import LEVEL_COLOR, LEVEL_LABEL, RiskAlert, RiskLevel
from .domain.targets import TargetKind


class Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class TargetInput(Camel):
    name: str = Field(min_length=1, max_length=200)
    kind: TargetKind = TargetKind.PERSON
    aliases: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    excluded_terms: list[str] = Field(default_factory=list)
    handles: dict[str, str] = Field(default_factory=dict)
    # Se ignora al editar: la baja y la reactivación tienen sus propias rutas (con motivo y bitácora).
    enabled: bool = True
    # Para la revisión en listas negras: fecha de nacimiento (AAAA-MM-DD o AAAA), nacionalidad y documentos.
    birth_date: str | None = Field(default=None, pattern=r"^\d{4}(-\d{2}-\d{2})?$")
    nationality: str | None = Field(default=None, max_length=64)
    # "rfc", "curp", "pasaporte" → valor.
    identifiers: dict[str, str] = Field(default_factory=dict)


class DeactivateInput(Camel):
    reason: str = Field(min_length=3, max_length=1000)


class TargetOut(Camel):
    id: uuid.UUID
    name: str
    kind: TargetKind
    aliases: list[str]
    keywords: list[str]
    excluded_terms: list[str]
    handles: dict[str, str]
    enabled: bool
    created_at: datetime
    birth_date: str | None = None
    nationality: str | None = None
    identifiers: dict[str, str] = Field(default_factory=dict)
    updated_at: datetime | None = None
    deactivated_at: datetime | None = None
    deactivated_by_email: str | None = None
    deactivation_reason: str | None = None

    _no_null = field_validator("identifiers", mode="before")(lambda v: v or {})


class MentionOut(Camel):
    id: uuid.UUID
    source: str
    url: str
    author: str
    author_name: str | None
    followers: int
    published_at: datetime
    text: str
    sentiment: str
    score: float
    severe: bool
    topic: str | None
    summary: str | None
    interactions: int
    # Lo cambió un analista; originalSentiment es lo que había dicho el análisis automático.
    corrected: bool = False
    original_sentiment: str | None = None
    corrected_by: str | None = None

    @classmethod
    def of(cls, m: db.Mention) -> "MentionOut":
        return cls(
            id=m.id, source=m.source, url=m.url, author=m.author_handle, author_name=m.author_name,
            followers=m.author_followers, published_at=m.published_at, text=m.text, sentiment=m.sentiment.lower(),
            score=m.sentiment_score, severe=m.is_severe_accusation, topic=m.topic, summary=m.summary,
            interactions=m.interactions, corrected=m.sentiment_corrected_at is not None,
            original_sentiment=m.original_sentiment.lower() if m.original_sentiment else None,
            corrected_by=m.sentiment_corrected_by,
        )


class SentimentCorrection(Camel):
    sentiment: Literal["negative", "neutral", "positive"]


class RiskOut(Camel):
    target_id: uuid.UUID
    at: datetime
    index: float
    level: RiskLevel
    label: str
    color: str
    media_score: float
    survey_score: float | None
    negativity: float
    severity: float
    volume_anomaly: float
    mentions: int
    positive: int
    negative: int
    neutral: int
    top_drivers: list[uuid.UUID]
    # Puntos que sumaron las coincidencias confirmadas en listas negras.
    watchlist_impact: float = 0

    @classmethod
    def of(cls, s: db.RiskSnapshot) -> "RiskOut":
        level = RiskLevel(s.level)
        return cls(
            target_id=s.target_id, at=s.at, index=s.index, level=level, label=LEVEL_LABEL[level],
            color=LEVEL_COLOR[level], media_score=s.media_score, survey_score=s.survey_score,
            negativity=s.negativity, severity=s.severity, volume_anomaly=s.volume_anomaly, mentions=s.mention_count,
            positive=s.positive, negative=s.negative, neutral=s.neutral,
            top_drivers=[uuid.UUID(str(d)) for d in s.top_drivers or []], watchlist_impact=s.watchlist_impact or 0,
        )


class AlertOut(Camel):
    id: int | None = None
    kind: str
    title: str
    message: str
    mention_id: uuid.UUID | None = None
    at: datetime | None = None

    @classmethod
    def of_alert(cls, a: RiskAlert) -> "AlertOut":
        return cls(kind=a.kind.value, title=a.title, message=a.message, mention_id=a.mention_id)


class SourceSentimentCount(Camel):
    source: str
    sentiment: str
    count: int


class Influencer(Camel):
    author: str
    followers: int
    mentions: int
    negative: int


class TopicCount(Camel):
    topic: str
    count: int


class BreakdownOut(Camel):
    by_source_and_sentiment: list[SourceSentimentCount]
    influencers: list[Influencer]
    topics: list[TopicCount]


class ConnectorStateOut(Camel):
    source: str
    value: str | None
    last_run_at: datetime | None
    last_error: str | None

    # Errores guardados antes de que se quitaran las llaves al registrarlos.
    _redact = field_validator("last_error")(lambda v: v and redact_secrets(v))


class SourceError(Camel):
    target_id: uuid.UUID
    target_name: str
    at: datetime | None
    error: str

    _redact = field_validator("error")(redact_secrets)


class SourceStatus(Camel):
    source: str
    configured: bool
    last_run_at: datetime | None = None
    last_mention_at: datetime | None = None
    mentions_last_day: int = 0
    errors: list[SourceError] = Field(default_factory=list)


class ChannelStatus(Camel):
    channel: str
    configured: bool


class SourcesOut(Camel):
    sources: list[SourceStatus]
    channels: list[ChannelStatus]


class SurveySubmission(Camel):
    survey_id: str
    answers: dict[str, str]


class SurveyResponseOut(Camel):
    id: uuid.UUID
    target_id: uuid.UUID
    survey_id: str
    submitted_at: datetime
    score: float | None
    level: str | None
    section_values: dict[str, int]
    answers: dict[str, str]


class SurveySummary(Camel):
    id: str
    name: str
    description: str
    scored: bool
    sections: int
