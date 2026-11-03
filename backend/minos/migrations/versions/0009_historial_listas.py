"""Cargas de listas propias (completas o de actualización) e historial de cambios de cada registro.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-03
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "watchlist_uploads",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(64), sa.ForeignKey("watchlist_sources.slug", ondelete="CASCADE"), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=True),
        sa.Column("at", TS, nullable=False),
        sa.Column("uploaded_by", sa.String(254), nullable=True),
        sa.Column("rows", sa.Integer(), nullable=False),
        sa.Column("added", sa.Integer(), nullable=False),
        sa.Column("status_changed", sa.Integer(), nullable=False),
        sa.Column("changed", sa.Integer(), nullable=False),
        sa.Column("unchanged", sa.Integer(), nullable=False),
        sa.Column("removed", sa.Integer(), nullable=False),
        sa.Column("entries", sa.Integer(), nullable=False),
    )
    op.create_index("ix_watchlist_uploads_source_at", "watchlist_uploads", ["source", "at"])
    op.create_table(
        "watchlist_changes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("upload_id", sa.BigInteger(), sa.ForeignKey("watchlist_uploads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("change", sa.String(16), nullable=False),
        sa.Column("fields", postgresql.JSONB(), nullable=False),
        sa.Column("at", TS, nullable=False),
    )
    op.create_index("ix_watchlist_changes_entry", "watchlist_changes", ["source", "external_id"])
    op.create_index("ix_watchlist_changes_upload", "watchlist_changes", ["upload_id"])


def downgrade() -> None:
    op.drop_index("ix_watchlist_changes_upload", table_name="watchlist_changes")
    op.drop_index("ix_watchlist_changes_entry", table_name="watchlist_changes")
    op.drop_table("watchlist_changes")
    op.drop_index("ix_watchlist_uploads_source_at", table_name="watchlist_uploads")
    op.drop_table("watchlist_uploads")
