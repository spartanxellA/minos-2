"""Aplicación FastAPI: API REST y WebSocket del tablero.

Con MINOS_ROLE=all (por omisión) también corre los workers de ingesta y riesgo en el mismo proceso; con
MINOS_ROLE=api solo sirve datos y los workers corren aparte (python -m minos.worker) comunicándose por Redis.

Correr en local:  uvicorn minos.main:app --reload --port 5080
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router, ws_router
from .auth import TokenValidator
from .config import Settings, get_settings
from .realtime import RiskHub
from .runtime import Runtime
from .surveys import SurveyCatalog

log = logging.getLogger("minos")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    if not settings.auth.authority and not settings.is_development:
        raise RuntimeError("Configura MINOS_AUTH__AUTHORITY: la API no corre sin autenticación fuera de development.")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = await Runtime.start(settings)
        hub = RiskHub()
        app.state.runtime = runtime
        app.state.db = runtime.db
        app.state.bus = runtime.bus
        app.state.hub = hub
        app.state.risk_engine = runtime.engine
        app.state.connectors = runtime.connectors
        # Los eventos en vivo llegan por el bus, vengan de este proceso o de los workers.
        runtime.spawn(runtime.bus.listen(hub.deliver), "live-events")
        if settings.role == "all":
            runtime.start_workers()
        elif not settings.redis_url:
            log.warning("MINOS_ROLE=api sin MINOS_REDIS_URL: el tablero no recibirá eventos de los workers.")
        if not settings.auth.authority:
            log.warning("Autenticación desactivada (development sin MINOS_AUTH__AUTHORITY).")
        try:
            yield
        finally:
            await runtime.stop()

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
