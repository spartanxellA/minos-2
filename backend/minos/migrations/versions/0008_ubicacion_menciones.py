"""Ubicación de cada mención para el mapa geográfico.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-30
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mentions", sa.Column("geo_country", sa.String(2), nullable=True))
    op.add_column("mentions", sa.Column("geo_region", sa.String(8), nullable=True))
    op.add_column("mentions", sa.Column("geo_city", sa.String(80), nullable=True))
    op.add_column("mentions", sa.Column("geo_lat", sa.Float(), nullable=True))
    op.add_column("mentions", sa.Column("geo_lon", sa.Float(), nullable=True))
    op.add_column("mentions", sa.Column("geo_precision", sa.String(8), nullable=True))
    op.add_column("mentions", sa.Column("geo_method", sa.String(16), nullable=True))
    op.create_index("ix_mentions_target_geo", "mentions", ["target_id", "geo_country", "geo_region"])


def downgrade() -> None:
    op.drop_index("ix_mentions_target_geo", table_name="mentions")
    for column in ("geo_method", "geo_precision", "geo_lon", "geo_lat", "geo_city", "geo_region", "geo_country"):
        op.drop_column("mentions", column)
