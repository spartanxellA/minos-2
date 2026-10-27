"""Listas negras: registros de cada lista, coincidencias por objetivo y datos extra del objetivo.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-27
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
J = postgresql.JSONB()


def upgrade() -> None:
    op.add_column("targets", sa.Column("birth_date", sa.String(10), nullable=True))
    op.add_column("targets", sa.Column("nationality", sa.String(64), nullable=True))
    op.add_column("targets", sa.Column("identifiers", J, nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.alter_column("targets", "identifiers", server_default=None)
    op.add_column("risk_snapshots", sa.Column("watchlist_impact", sa.Float(), nullable=False, server_default="0"))

    op.create_table(
        "watchlist_sources",
        sa.Column("slug", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("custom", sa.Boolean(), nullable=False),
        sa.Column("version", sa.String(64), nullable=True),
        sa.Column("entry_count", sa.Integer(), nullable=False),
        sa.Column("last_checked_at", TS, nullable=True),
        sa.Column("last_changed_at", TS, nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("uploaded_by", sa.String(254), nullable=True),
    )
    op.create_table(
        "watchlist_entries",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(64), sa.ForeignKey("watchlist_sources.slug", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("aliases", J, nullable=False),
        sa.Column("birth_dates", J, nullable=False),
        sa.Column("nationalities", J, nullable=False),
        sa.Column("identifiers", J, nullable=False),
        sa.Column("programs", J, nullable=False),
        sa.Column("listed_on", sa.String(32), nullable=True),
        sa.Column("status", sa.String(64), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
    )
    op.create_index("ux_watchlist_entries_source_external", "watchlist_entries", ["source", "external_id"], unique=True)

    op.create_table(
        "screening_matches",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("target_id", sa.Uuid(), sa.ForeignKey("targets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("source_name", sa.String(200), nullable=False),
        sa.Column("listed_name", sa.String(500), nullable=False),
        sa.Column("matched_name", sa.String(500), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("strength", sa.String(16), nullable=False),
        sa.Column("reasons", J, nullable=False),
        sa.Column("entry", J, nullable=False),
        sa.Column("entry_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("first_seen_at", TS, nullable=False),
        sa.Column("last_seen_at", TS, nullable=False),
        sa.Column("reviewed_at", TS, nullable=True),
        sa.Column("reviewed_by_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_by_email", sa.String(254), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
    )
    op.create_index("ux_screening_target_entry", "screening_matches", ["target_id", "source", "external_id"], unique=True)
    op.create_index("ix_screening_status", "screening_matches", ["status"])

    op.create_table(
        "screening_state",
        sa.Column("target_id", sa.Uuid(), sa.ForeignKey("targets.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("screened_at", TS, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("screening_state")
    op.drop_table("screening_matches")
    op.drop_table("watchlist_entries")
    op.drop_table("watchlist_sources")
    op.drop_column("risk_snapshots", "watchlist_impact")
    op.drop_column("targets", "identifiers")
    op.drop_column("targets", "nationality")
    op.drop_column("targets", "birth_date")
