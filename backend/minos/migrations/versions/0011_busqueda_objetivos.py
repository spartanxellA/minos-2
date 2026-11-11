"""Texto de búsqueda de los objetivos (nombre y alias sin acentos) e índice para el selector del tablero.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-10
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from minos.db import target_search_text

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("targets", sa.Column("search_text", sa.Text(), nullable=False, server_default=""))
    op.create_index("ix_targets_enabled_kind_name", "targets", ["enabled", "kind", "name"])
    targets = sa.table("targets", sa.column("id", sa.Uuid()), sa.column("name", sa.String()),
                       sa.column("aliases", sa.JSON()), sa.column("search_text", sa.Text()))
    conn = op.get_bind()
    for row in conn.execute(sa.select(targets.c.id, targets.c.name, targets.c.aliases)).all():
        conn.execute(targets.update().where(targets.c.id == row.id)
                     .values(search_text=target_search_text(row.name, row.aliases)))


def downgrade() -> None:
    op.drop_index("ix_targets_enabled_kind_name", "targets")
    op.drop_column("targets", "search_text")
