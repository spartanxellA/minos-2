"""Ajustes de autogenerate compartidos por env.py y las pruebas."""
from minos.db import UtcDateTime

# Índices que crea TimescaleDB por su cuenta; no son parte de los modelos y autogenerate no debe borrarlos.
TIMESCALE_INDEXES = {"risk_snapshots_at_idx"}


def include_object(obj, name, type_, reflected, compare_to):
    return not (type_ == "index" and reflected and compare_to is None and name in TIMESCALE_INDEXES)


def render_item(type_, obj, autogen_context):
    """Las migraciones son solo para PostgreSQL: se escriben con tipos estándar, sin importar minos.db."""
    if type_ == "type" and isinstance(obj, UtcDateTime):
        return "sa.DateTime(timezone=True)"
    variants = getattr(obj, "_variant_mapping", None) or {}
    if type_ == "type" and type(variants.get("postgresql")).__name__ == "JSONB":
        autogen_context.imports.add("from sqlalchemy.dialects import postgresql")
        return "postgresql.JSONB()"
    return False
