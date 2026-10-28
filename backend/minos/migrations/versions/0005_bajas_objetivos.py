"""Baja lógica de objetivos: cuándo, quién y por qué.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-28
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("targets", sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("targets", sa.Column("deactivated_by_email", sa.String(254), nullable=True))
    op.add_column("targets", sa.Column("deactivation_reason", sa.Text(), nullable=True))
    op.add_column("targets", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    # Los que ya estaban apagados quedan como dados de baja, con la fecha de la migración.
    op.execute("UPDATE targets SET deactivated_at = now() WHERE enabled = false")


def downgrade() -> None:
    op.drop_column("targets", "updated_at")
    op.drop_column("targets", "deactivation_reason")
    op.drop_column("targets", "deactivated_by_email")
    op.drop_column("targets", "deactivated_at")
