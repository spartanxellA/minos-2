"""Contratos JSON de la API, en camelCase para el tablero."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from . import db
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
    enabled: bool = True


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

    @classmethod
    def of(cls, m: db.Mention) -> "MentionOut":
        return cls(
            id=m.id, source=m.source, url=m.url, author=m.author_handle, author_name=m.author_name,
            followers=m.author_followers, published_at=m.published_at, text=m.text, sentiment=m.sentiment.lower(),
            score=m.sentiment_score, severe=m.is_severe_accusation, topic=m.topic, summary=m.summary,
            interactions=m.interactions,
        )


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

    @classmethod
    def of(cls, s: db.RiskSnapshot) -> "RiskOut":
        level = RiskLevel(s.level)
        return cls(
            target_id=s.target_id, at=s.at, index=s.index, level=level, label=LEVEL_LABEL[level],
            color=LEVEL_COLOR[level], media_score=s.media_score, survey_score=s.survey_score,
            negativity=s.negativity, severity=s.severity, volume_anomaly=s.volume_anomaly, mentions=s.mention_count,
            positive=s.positive, negative=s.negative, neutral=s.neutral,
            top_drivers=[uuid.UUID(str(d)) for d in s.top_drivers or []],
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


class SurveySummary(Camel):
    id: str
    name: str
    description: str
    scored: bool
    sections: int
