"""Configuración por variables de entorno con prefijo MINOS_ (secciones anidadas con "__").

Ejemplos: MINOS_DATABASE_URL, MINOS_NLP_URL, MINOS_CONNECTORS__X__BEARER_TOKEN, MINOS_DEMO__ENABLED.
"""
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _seconds(value):
    """Las duraciones se escriben en segundos ("300") o en ISO 8601 ("PT5M")."""
    if isinstance(value, str) and value.strip().replace(".", "", 1).isdigit():
        return float(value)
    return value


Duration = Annotated[timedelta, BeforeValidator(_seconds)]


class RssSettings(BaseModel):
    use_google_news_search: bool = True
    google_news_locale: str = "hl=es-419&gl=MX&ceid=MX:es-419"
    feeds: list[str] = Field(default_factory=list)
    poll_interval: Duration = timedelta(minutes=5)


class XSettings(BaseModel):
    bearer_token: str = ""
    max_results: int = 100
    poll_interval: Duration = timedelta(minutes=15)
    exclude_retweets: bool = True


class YouTubeSettings(BaseModel):
    api_key: str = ""
    region_code: str = "MX"
    relevance_language: str = "es"
    # search.list cuesta 100 unidades; con la cuota gratuita de 10,000 al día conviene no bajar de 30 min.
    poll_interval: Duration = timedelta(minutes=30)


class BlueskySettings(BaseModel):
    service: str = "https://bsky.social"
    # Cuenta de servicio con contraseña de aplicación: la búsqueda requiere sesión.
    identifier: str = ""
    app_password: str = ""
    poll_interval: Duration = timedelta(minutes=5)


class ConnectorSettings(BaseModel):
    rss: RssSettings = RssSettings()
    x: XSettings = XSettings()
    youtube: YouTubeSettings = YouTubeSettings()
    bluesky: BlueskySettings = BlueskySettings()


class DemoSettings(BaseModel):
    # Menciones sintéticas para ver el tablero en vivo sin llaves de API. Nunca en producción.
    enabled: bool = False
    poll_interval: Duration = timedelta(seconds=20)


class IngestionSettings(BaseModel):
    tick: Duration = timedelta(seconds=30)
    max_mentions_per_run: int = 300
    # Ventana para descartar el mismo texto publicado de nuevo (retuits, notas replicadas).
    duplicate_window: Duration = timedelta(days=3)


class RiskEngineSettings(BaseModel):
    # Recalcula todos los objetivos al menos con esta frecuencia, aunque no lleguen menciones.
    full_recompute_every: Duration = timedelta(minutes=1)
    window: Duration = timedelta(hours=24)
    baseline_days: int = 28
    # Días mínimos de historia antes de que el volumen anómalo cuente (evita falsos picos al dar de alta un objetivo).
    min_baseline_days: int = 7
    media_weight: float = 0.6
    survey_weight: float = 0.4


class AuthSettings(BaseModel):
    # Emisor OIDC (Keycloak, Entra ID, Auth0...). Vacío solo se permite en development.
    authority: str = ""
    audience: str = "minos-api"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MINOS_", env_nested_delimiter="__", env_file=".env", extra="ignore")

    env: str = "development"
    database_url: str = "postgresql+asyncpg://minos:minos@localhost:5432/minos"
    nlp_url: str = ""
    cors_origins: list[str] = ["http://localhost:3000"]
    surveys_path: Path = DATA_DIR / "surveys.json"
    # Los workers corren dentro de la API; con False la API solo sirve datos (útil al escalar workers aparte).
    run_workers: bool = True
    # Crea las tablas desde los modelos al arrancar (pruebas con SQLite). En PostgreSQL se usan las migraciones.
    create_schema: bool = False

    auth: AuthSettings = AuthSettings()
    demo: DemoSettings = DemoSettings()
    ingestion: IngestionSettings = IngestionSettings()
    risk_engine: RiskEngineSettings = RiskEngineSettings()
    connectors: ConnectorSettings = ConnectorSettings()

    @property
    def is_development(self) -> bool:
        return self.env.lower() == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
