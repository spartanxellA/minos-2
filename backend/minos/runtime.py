"""Las piezas que comparten la API y el proceso de workers: base de datos, bus, conectores y pipeline."""
import asyncio
import contextlib
import logging
from dataclasses import dataclass, field

import httpx

from .analysis import NlpServiceAnalyzer
from .bus import Bus, create_bus
from .config import Settings
from .connectors import MentionConnector, build_connectors, new_http_client
from .db import Database
from .pipeline import IngestionWorker, RiskEngine

log = logging.getLogger("minos")


@dataclass
class Runtime:
    settings: Settings
    db: Database
    bus: Bus
    http: httpx.AsyncClient
    connectors: list[MentionConnector]
    engine: RiskEngine
    ingestion: IngestionWorker
    _tasks: list[asyncio.Task] = field(default_factory=list)

    @classmethod
    async def start(cls, settings: Settings) -> "Runtime":
        database = Database(settings.database_url)
        if settings.create_schema:
            await database.create_schema()
        bus = create_bus(settings.redis_url)
        http = new_http_client()
        connectors = build_connectors(settings, http)
        engine = RiskEngine(database, bus, settings.risk_engine)
        analyzer = NlpServiceAnalyzer(http, settings.nlp_url)
        ingestion = IngestionWorker(database, connectors, analyzer, bus, settings.ingestion)
        return cls(settings, database, bus, http, connectors, engine, ingestion)

    def spawn(self, coro, name: str) -> None:
        self._tasks.append(asyncio.create_task(coro, name=name))

    def start_workers(self) -> None:
        active = [c.source for c in self.connectors if c.is_configured]
        log.info("Workers en marcha. Conectores activos: %s", ", ".join(active) or "ninguno")
        self.spawn(self.ingestion.run(), "ingestion")
        self.spawn(self.engine.run(), "risk-engine")

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await t
        await self.http.aclose()
        await self.bus.close()
        await self.db.dispose()
