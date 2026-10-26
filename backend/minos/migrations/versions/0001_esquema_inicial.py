"""Esquema inicial de minOS 2.0.

risk_snapshots se convierte en hypertable de TimescaleDB cuando la extensión está disponible (la imagen
timescale/timescaledb de docker-compose la trae); en un PostgreSQL sin TimescaleDB queda como tabla normal.
Por eso su llave primaria es (id, at): TimescaleDB exige que toda llave única incluya la columna de tiempo.

Revision ID: 0001
Revises:
Create Date: 2026-10-26
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)


def _target_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["target_id"], ["targets.id"], ondelete="CASCADE")


def upgrade() -> None:
    op.create_table(
        "targets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("aliases", postgresql.JSONB(), nullable=False),
        sa.Column("keywords", postgresql.JSONB(), nullable=False),
        sa.Column("excluded_terms", postgresql.JSONB(), nullable=False),
        sa.Column("handles", postgresql.JSONB(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )

    op.create_table(
        "mentions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(512), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("author_handle", sa.String(200), nullable=False),
        sa.Column("author_name", sa.String(200)),
        sa.Column("author_followers", sa.BigInteger(), nullable=False),
        sa.Column("author_verified", sa.Boolean(), nullable=False),
        sa.Column("published_at", TS, nullable=False),
        sa.Column("ingested_at", TS, nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("language", sa.String(16)),
        sa.Column("likes", sa.BigInteger(), nullable=False),
        sa.Column("shares", sa.BigInteger(), nullable=False),
        sa.Column("replies", sa.BigInteger(), nullable=False),
        sa.Column("views", sa.BigInteger(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("sentiment", sa.String(16), nullable=False),
        sa.Column("sentiment_score", sa.Float(), nullable=False),
        sa.Column("is_severe_accusation", sa.Boolean(), nullable=False),
        sa.Column("topic", sa.String(200)),
        sa.Column("summary", sa.Text()),
        sa.Column("analyzer", sa.String(64), nullable=False),
        sa.Column("raw", postgresql.JSONB()),
        _target_fk(),
    )
    op.create_index("ux_mentions_target_source_external", "mentions", ["target_id", "source", "external_id"], unique=True)
    op.create_index("ix_mentions_target_fingerprint", "mentions", ["target_id", "fingerprint"])
    op.create_index("ix_mentions_target_published", "mentions", ["target_id", "published_at"])

    op.create_table(
        "connector_cursors",
        sa.Column("target_id", sa.Uuid(), primary_key=True),
        sa.Column("source", sa.String(32), primary_key=True),
        sa.Column("value", sa.String(200)),
        sa.Column("last_run_at", TS),
        sa.Column("last_error", sa.Text()),
        _target_fk(),
    )

    op.create_table(
        "risk_snapshots",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("at", TS, nullable=False),
        sa.Column("index", sa.Float(), nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("media_score", sa.Float(), nullable=False),
        sa.Column("survey_score", sa.Float()),
        sa.Column("negativity", sa.Float(), nullable=False),
        sa.Column("severity", sa.Float(), nullable=False),
        sa.Column("volume_anomaly", sa.Float(), nullable=False),
        sa.Column("mention_count", sa.Integer(), nullable=False),
        sa.Column("positive", sa.Integer(), nullable=False),
        sa.Column("negative", sa.Integer(), nullable=False),
        sa.Column("neutral", sa.Integer(), nullable=False),
        sa.Column("top_drivers", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", "at"),
        _target_fk(),
    )
    op.create_index("ix_risk_target_at", "risk_snapshots", ["target_id", "at"])

    op.create_table(
        "survey_responses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("survey_id", sa.String(64), nullable=False),
        sa.Column("submitted_at", TS, nullable=False),
        sa.Column("answers", postgresql.JSONB(), nullable=False),
        sa.Column("score", sa.Float()),
        sa.Column("level", sa.String(16)),
        sa.Column("section_values", postgresql.JSONB(), nullable=False),
        _target_fk(),
    )
    op.create_index("ix_survey_target_submitted", "survey_responses", ["target_id", "submitted_at"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("at", TS, nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("mention_id", sa.Uuid()),
        _target_fk(),
    )
    op.create_index("ix_alerts_target_at", "alerts", ["target_id", "at"])

    # TimescaleDB: la serie del índice crece con cada recálculo; particionarla por tiempo mantiene rápidas las
    # gráficas y permite políticas de retención y compresión más adelante.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb') THEN
                CREATE EXTENSION IF NOT EXISTS timescaledb;
                PERFORM create_hypertable('risk_snapshots', 'at', chunk_time_interval => INTERVAL '7 days');
            ELSE
                RAISE NOTICE 'TimescaleDB no está disponible: risk_snapshots queda como tabla normal';
            END IF;
        END $$;
    """)


def downgrade() -> None:
    for table in ("alerts", "survey_responses", "risk_snapshots", "connector_cursors", "mentions", "targets"):
        op.drop_table(table)
