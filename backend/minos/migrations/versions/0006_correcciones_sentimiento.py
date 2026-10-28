"""Corrección del sentimiento de una mención por un analista.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-28
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mentions", sa.Column("original_sentiment", sa.String(16), nullable=True))
    op.add_column("mentions", sa.Column("sentiment_corrected_by", sa.String(254), nullable=True))
    op.add_column("mentions", sa.Column("sentiment_corrected_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_mentions_target_corrected", "mentions", ["target_id", "sentiment_corrected_at"])


def downgrade() -> None:
    op.drop_index("ix_mentions_target_corrected", table_name="mentions")
    op.drop_column("mentions", "sentiment_corrected_at")
    op.drop_column("mentions", "sentiment_corrected_by")
    op.drop_column("mentions", "original_sentiment")
