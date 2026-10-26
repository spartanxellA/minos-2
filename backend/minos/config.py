"""Configuración por variables de entorno con prefijo MINOS_ (secciones anidadas con "__").

Ejemplos: MINOS_DATABASE_URL, MINOS_NLP_URL, MINOS_CONNECTORS__X__BEARER_TOKEN, MINOS_DEMO__ENABLED.
"""
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

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


class JetstreamSettings(BaseModel):
    # Todas las publicaciones nuevas de Bluesky en tiempo real, filtradas aquí contra los objetivos. No requiere cuenta.
    enabled: bool = False
    url: str = "wss://jetstream2.us-east.bsky.network/subscribe"
    # Perfil del autor (cuenta y seguidores) para las publicaciones que coinciden.
    profile_api: str = "https://public.api.bsky.app"
    # Al arrancar se retrocede este tiempo para no perder lo publicado mientras el worker estaba detenido.
    replay: Duration = timedelta(minutes=5)
    flush_every: Duration = timedelta(seconds=5)


class RedditSettings(BaseModel):
    # App "script" o "web" de https://www.reddit.com/prefs/apps (OAuth sin usuario).
    client_id: str = ""
    client_secret: str = ""
    # Reddit exige un User-Agent propio que identifique la app y a su responsable, por ejemplo "minOS/2.0 (by u/cuenta)".
    user_agent: str = "minOS/2.0"
    # Subreddits donde buscar (sin "r/"); vacío busca en todo Reddit.
    subreddits: list[str] = Field(default_factory=list)
    poll_interval: Duration = timedelta(minutes=10)


class MetaSettings(BaseModel):
    # Token de usuario del sistema (Meta Business) o de página, con pages_read_engagement,
    # pages_read_user_content e instagram_manage_comments. Las páginas se configuran por objetivo en sus cuentas:
    # "facebook" → id de la página, "instagram" → id de la cuenta profesional de Instagram.
    access_token: str = ""
    graph_url: str = "https://graph.facebook.com/v23.0"
    # Publicaciones recientes revisadas por ronda (y hasta 50 comentarios de cada una).
    recent_posts: int = 25
    poll_interval: Duration = timedelta(minutes=10)


class ConnectorSettings(BaseModel):
    rss: RssSettings = RssSettings()
    x: XSettings = XSettings()
    youtube: YouTubeSettings = YouTubeSettings()
    bluesky: BlueskySettings = BlueskySettings()
    jetstream: JetstreamSettings = JetstreamSettings()
    reddit: RedditSettings = RedditSettings()
    meta: MetaSettings = MetaSettings()


class DemoSettings(BaseModel):
    # Menciones sintéticas para ver el tablero en vivo sin llaves de API. Nunca en producción.
    enabled: bool = False
    poll_interval: Duration = timedelta(seconds=20)


class IngestionSettings(BaseModel):
    tick: Duration = timedelta(seconds=30)
    max_mentions_per_run: int = 300
    # Ventana para descartar el mismo texto publicado de nuevo (retuits, notas replicadas).
    duplicate_window: Duration = timedelta(days=3)
    # Vencimiento del candado por objetivo y fuente: si un worker muere a media consulta, otro la retoma después.
    lock_ttl: Duration = timedelta(minutes=10)


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
    # "all": API y workers en un proceso (desarrollo). "api": solo HTTP y WebSocket. Los workers (ingesta y motor de
    # riesgo) corren aparte con "python -m minos.worker". Separarlos requiere Redis para pasarse eventos y trabajo.
    role: Literal["all", "api"] = "all"
    redis_url: str = ""
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
