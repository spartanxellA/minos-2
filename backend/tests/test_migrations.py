import asyncio

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from minos.db import Base
from minos.migrations.hooks import include_object

from conftest import POSTGRES_URL, migrate, needs_postgres, reset_postgres


def _query(sql: str):
    async def run():
        engine = create_async_engine(POSTGRES_URL)
        async with engine.connect() as conn:
            rows = (await conn.execute(text(sql))).all()
        await engine.dispose()
        return rows

    return asyncio.run(run())


def _diff():
    async def run():
        engine = create_async_engine(POSTGRES_URL)
        async with engine.connect() as conn:
            diff = await conn.run_sync(
                lambda c: compare_metadata(MigrationContext.configure(c, opts={"compare_type": True, "include_object": include_object}), Base.metadata)
            )
        await engine.dispose()
        return diff

    return asyncio.run(run())


@needs_postgres
def test_migrations_build_the_same_schema_as_the_models():
    reset_postgres(POSTGRES_URL)
    migrate(POSTGRES_URL)
    assert _diff() == []


@needs_postgres
def test_migrations_go_down_and_up_again():
    reset_postgres(POSTGRES_URL)
    migrate(POSTGRES_URL)
    migrate(POSTGRES_URL, "base", down=True)
    assert _query("SELECT to_regclass('public.targets')") == [(None,)]
    migrate(POSTGRES_URL)
    assert _query("SELECT version_num FROM alembic_version") == [("0001",)]


@needs_postgres
def test_risk_snapshots_is_a_hypertable_when_timescaledb_exists():
    reset_postgres(POSTGRES_URL)
    migrate(POSTGRES_URL)
    if not _query("SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb'"):
        return
    rows = _query("SELECT hypertable_name FROM timescaledb_information.hypertables")
    assert ("risk_snapshots",) in rows
