"""Entorno de Alembic. La URL sale de MINOS_DATABASE_URL, igual que en la API."""
import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from minos.config import get_settings
from minos.db import Base
from minos.migrations.hooks import include_object, render_item

target_metadata = Base.metadata


def _url() -> str:
    return context.config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, compare_type=True, render_item=render_item, include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True, render_item=render_item, include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    asyncio.run(run_online())
