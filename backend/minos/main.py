"""Aplicación FastAPI: API REST, WebSocket del tablero y workers de ingesta y riesgo en el mismo proceso.

Correr en local:  uvicorn minos.main:app --reload --port 5080
"""
import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .analysis import NlpServiceAnalyzer
from .api import router, ws_router
from .auth import TokenValidator
from .config import Settings, get_settings
from .connectors import build_connectors, new_http_client
from .db import Database
from .pipeline import IngestionWorker, RiskEngine
from .realtime import RiskHub
from .surveys import SurveyCatalog

log = logging.getLogger("minos")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    if not settings.auth.authority and not settings.is_development:
        raise RuntimeError("Configura MINOS_AUTH__AUTHORITY: la API no corre sin autenticación fuera de development.")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database = Database(settings.database_url)
        await database.create_schema()
        http = new_http_client()
        hub = RiskHub()
        engine = RiskEngine(database, hub, settings.risk_engine)
        app.state.db = database
        app.state.hub = hub
        app.state.risk_engine = engine
        app.state.connectors = build_connectors(settings, http)

        tasks = []
        if settings.run_workers:
            analyzer = NlpServiceAnalyzer(http, settings.nlp_url)
            ingestion = IngestionWorker(database, app.state.connectors, analyzer, hub, settings.ingestion, engine.enqueue)
            app.state.ingestion = ingestion
            tasks = [asyncio.create_task(ingestion.run(), name="ingestion"),
                     asyncio.create_task(engine.run(), name="risk-engine")]
        active = [c.source for c in app.state.connectors if c.is_configured]
        log.info("minOS listo. Conectores activos: %s", ", ".join(active) or "ninguno")
        if not settings.auth.authority:
            log.warning("Autenticación desactivada (development sin MINOS_AUTH__AUTHORITY).")
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            for t in tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await t
            await http.aclose()
            await database.dispose()

    app = FastAPI(title="minOS API", version="2.0.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.auth = TokenValidator(settings.auth)
    app.state.surveys = SurveyCatalog(settings.surveys_path)
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
    )

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    app.include_router(router)
    app.include_router(ws_router)
    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
