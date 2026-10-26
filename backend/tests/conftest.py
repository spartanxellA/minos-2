"""Por omisión las pruebas usan SQLite. Con MINOS_TEST_POSTGRES_URL (como en CI) también corren las de migraciones
y la API se prueba sobre PostgreSQL migrado con Alembic."""
import asyncio
import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

POSTGRES_URL = os.getenv("MINOS_TEST_POSTGRES_URL", "")
needs_postgres = pytest.mark.skipif(not POSTGRES_URL, reason="define MINOS_TEST_POSTGRES_URL para probar contra PostgreSQL")


def reset_postgres(url: str) -> None:
    async def run():
        from sqlalchemy.exc import DBAPIError

        engine = create_async_engine(url)
        # Los trabajos en segundo plano de TimescaleDB leen el catálogo y a veces chocan con el DROP (deadlock);
        # Postgres cancela una de las dos transacciones, así que basta con reintentar.
        for attempt in range(5):
            try:
                async with engine.begin() as conn:
                    await conn.execute(text("DROP SCHEMA public CASCADE"))
                    await conn.execute(text("CREATE SCHEMA public"))
                break
            except DBAPIError as ex:
                if "deadlock" not in str(ex) or attempt == 4:
                    raise
                await asyncio.sleep(0.2 * (attempt + 1))
        await engine.dispose()

    asyncio.run(run())


def migrate(url: str, revision: str = "head", down: bool = False) -> None:
    from alembic import command

    from minos.migrate import config

    cfg = config()
    cfg.set_main_option("sqlalchemy.url", url)
    (command.downgrade if down else command.upgrade)(cfg, revision)
