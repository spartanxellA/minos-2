"""Esquema en PostgreSQL (SQLAlchemy 2, asyncpg). Las listas y diccionarios van en columnas jsonb."""
import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, BigInteger, Integer, DateTime, Float, ForeignKey, Index, String, Text, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .domain.mentions import MentionAnalysis, MentionDraft, fingerprint
from .domain.targets import MonitoredTarget, TargetKind

Json = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


class UtcDateTime(TypeDecorator):
    """Fecha con zona horaria; garantiza UTC al leer aunque la base no guarde la zona (SQLite en pruebas)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value


class Base(DeclarativeBase):
    pass


class Target(Base):
    __tablename__ = "targets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32), default=TargetKind.PERSON.value)
    aliases: Mapped[list[str]] = mapped_column(Json, default=list)
    keywords: Mapped[list[str]] = mapped_column(Json, default=list)
    excluded_terms: Mapped[list[str]] = mapped_column(Json, default=list)
    handles: Mapped[dict[str, str]] = mapped_column(Json, default=dict)
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    def to_domain(self) -> MonitoredTarget:
        return MonitoredTarget(
            id=self.id, name=self.name, kind=TargetKind(self.kind), aliases=list(self.aliases or []),
            keywords=list(self.keywords or []), excluded_terms=list(self.excluded_terms or []),
            handles=dict(self.handles or {}), enabled=self.enabled,
        )


class Mention(Base):
    __tablename__ = "mentions"
    __table_args__ = (
        Index("ux_mentions_target_source_external", "target_id", "source", "external_id", unique=True),
        Index("ix_mentions_target_fingerprint", "target_id", "fingerprint"),
        Index("ix_mentions_target_published", "target_id", "published_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    target_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("targets.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(512))
    url: Mapped[str] = mapped_column(Text)
    author_handle: Mapped[str] = mapped_column(String(200))
    author_name: Mapped[str | None] = mapped_column(String(200))
    author_followers: Mapped[int] = mapped_column(BigInteger, default=0)
    author_verified: Mapped[bool] = mapped_column(default=False)
    published_at: Mapped[datetime] = mapped_column(UtcDateTime)
    ingested_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    text: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(16))
    likes: Mapped[int] = mapped_column(BigInteger, default=0)
    shares: Mapped[int] = mapped_column(BigInteger, default=0)
    replies: Mapped[int] = mapped_column(BigInteger, default=0)
    views: Mapped[int] = mapped_column(BigInteger, default=0)
    fingerprint: Mapped[str] = mapped_column(String(64))
    sentiment: Mapped[str] = mapped_column(String(16))
    sentiment_score: Mapped[float] = mapped_column(Float, default=0)
    is_severe_accusation: Mapped[bool] = mapped_column(default=False)
    topic: Mapped[str | None] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text)
    analyzer: Mapped[str] = mapped_column(String(64), default="lexicon")
    raw: Mapped[dict | None] = mapped_column(Json)

    @property
    def interactions(self) -> int:
        return (self.likes or 0) + (self.shares or 0) + (self.replies or 0)

    @classmethod
    def create(cls, target_id: uuid.UUID, draft: MentionDraft, analysis: MentionAnalysis) -> "Mention":
        e = draft.engagement
        return cls(
            id=uuid.uuid4(), target_id=target_id, source=draft.source, external_id=draft.external_id, url=draft.url,
            author_handle=draft.author.handle, author_name=draft.author.display_name,
            author_followers=draft.author.followers, author_verified=draft.author.verified,
            published_at=draft.published_at, ingested_at=utcnow(), text=draft.text, language=draft.language,
            likes=e.likes, shares=e.shares, replies=e.replies, views=e.views, fingerprint=fingerprint(draft.text),
            sentiment=analysis.sentiment.value, sentiment_score=analysis.score,
            is_severe_accusation=analysis.severe_accusation, topic=analysis.topic and analysis.topic[:200], summary=analysis.summary,
            analyzer=analysis.analyzer, raw=draft.raw,
        )


class ConnectorState(Base):
    """Cursor por objetivo y fuente, con la última corrida y el último error (tablero de salud)."""

    __tablename__ = "connector_cursors"

    target_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("targets.id", ondelete="CASCADE"), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[str | None] = mapped_column(String(200))
    last_run_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    last_error: Mapped[str | None] = mapped_column(Text)


class RiskSnapshot(Base):
    # En PostgreSQL la llave primaria es (id, at) porque la tabla es hypertable de TimescaleDB (migración 0001);
    # para el ORM basta con id, que es único.
    __tablename__ = "risk_snapshots"
    __table_args__ = (Index("ix_risk_target_at", "target_id", "at"),)

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    target_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("targets.id", ondelete="CASCADE"))
    at: Mapped[datetime] = mapped_column(UtcDateTime)
    index: Mapped[float] = mapped_column(Float)
    level: Mapped[str] = mapped_column(String(16))
    media_score: Mapped[float] = mapped_column(Float)
    survey_score: Mapped[float | None] = mapped_column(Float)
    negativity: Mapped[float] = mapped_column(Float)
    severity: Mapped[float] = mapped_column(Float)
    volume_anomaly: Mapped[float] = mapped_column(Float)
    mention_count: Mapped[int] = mapped_column(default=0)
    positive: Mapped[int] = mapped_column(default=0)
    negative: Mapped[int] = mapped_column(default=0)
    neutral: Mapped[int] = mapped_column(default=0)
    top_drivers: Mapped[list[str]] = mapped_column(Json, default=list)


class SurveyResponse(Base):
    __tablename__ = "survey_responses"
    __table_args__ = (Index("ix_survey_target_submitted", "target_id", "submitted_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    target_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("targets.id", ondelete="CASCADE"))
    survey_id: Mapped[str] = mapped_column(String(64))
    submitted_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    # Respuestas: id de pregunta → valor de la opción ("A", "B", "C").
    answers: Mapped[dict[str, str]] = mapped_column(Json, default=dict)
    score: Mapped[float | None] = mapped_column(Float)
    level: Mapped[str | None] = mapped_column(String(16))
    section_values: Mapped[dict[str, int]] = mapped_column(Json, default=dict)


class AlertRecord(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_target_at", "target_id", "at"),)

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    target_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("targets.id", ondelete="CASCADE"))
    at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    kind: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    mention_id: Mapped[uuid.UUID | None] = mapped_column()


class Database:
    def __init__(self, url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(url, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def create_schema(self) -> None:
        """Crea las tablas directo desde los modelos. Solo para pruebas; en serio se usa python -m minos.migrate."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()

    def session(self) -> AsyncSession:
        return self.sessions()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Siempre en minúsculas: es el nombre de usuario.
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(16))
    password_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(default=True)
    failed_logins: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UtcDateTime)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(UtcDateTime)


class UserSession(Base):
    """Sesión iniciada. Solo se guarda el SHA-256 del token: una copia de la base no permite entrar."""

    __tablename__ = "user_sessions"
    __table_args__ = (Index("ix_user_sessions_user", "user_id"),)

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
