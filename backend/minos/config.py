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
    # Un cambio de tendencia o un pico se sigue cumpliendo en cada recálculo; se registra y avisa una vez en este lapso.
    alert_cooldown: Duration = timedelta(hours=6)


class EmailSettings(BaseModel):
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    from_addr: str = ""
    to: list[str] = Field(default_factory=list)
    # STARTTLS en el puerto 587; con 465 se usa TLS directo.
    starttls: bool = True


class WebhookSettings(BaseModel):
    # Recibe un JSON con la alerta; el campo "text" lo entienden los webhooks entrantes de Slack y Teams.
    urls: list[str] = Field(default_factory=list)
    # Si se define, cada envío lleva X-Minos-Signature: sha256=HMAC(secreto, cuerpo).
    secret: str = ""


class WhatsAppSettings(BaseModel):
    # WhatsApp Cloud API. Fuera de una conversación abierta solo se pueden mandar plantillas aprobadas por Meta;
    # la plantilla recibe tres variables: objetivo, título y detalle de la alerta.
    access_token: str = ""
    phone_number_id: str = ""
    to: list[str] = Field(default_factory=list)
    template: str = "minos_alerta"
    language: str = "es_MX"
    graph_url: str = "https://graph.facebook.com/v23.0"


class NotificationSettings(BaseModel):
    # Dirección del tablero para el enlace de cada aviso.
    dashboard_url: str = "http://localhost:3000"
    timeout: Duration = timedelta(seconds=15)
    email: EmailSettings = EmailSettings()
    webhook: WebhookSettings = WebhookSettings()
    whatsapp: WhatsAppSettings = WhatsAppSettings()


class WatchlistSettings(BaseModel):
    # Descarga de las listas oficiales y revisión de los objetivos contra ellas (en el proceso de workers).
    enabled: bool = True
    # Listas oficiales activas (ver minos.watchlists.sources): ofac-sdn, ofac-cons, un-sc, eu-fsf, uk-fcdo, sat-69b,
    # worldbank. Las listas propias (PEP, UIF…) se suben desde el tablero y no dependen de esto.
    sources: list[str] = Field(default_factory=lambda: [
        "ofac-sdn", "ofac-cons", "un-sc", "eu-fsf", "uk-fcdo", "sat-69b", "worldbank",
    ])
    # Para cambiar la dirección de descarga de una lista: {"uk-fcdo": "https://…"}.
    urls: dict[str, str] = Field(default_factory=dict)
    # Llave de la API de empresas inhabilitadas del Banco Mundial; sin ella esa lista no se descarga.
    worldbank_api_key: str = ""
    # Si una descarga falla, se reintenta después de este lapso (y no en cada vuelta).
    retry_after: Duration = timedelta(hours=1)
    download_timeout: Duration = timedelta(minutes=3)
    # Cada cuánto se buscan objetivos nuevos o cambiados para revisarlos.
    screen_every: Duration = timedelta(seconds=30)


class AuthSettings(BaseModel):
    # "local": cuentas de minOS con correo y contraseña. "off": sin inicio de sesión, solo en development.
    mode: Literal["local", "off"] = "local"
    session_ttl: Duration = timedelta(days=7)
    # Sin actividad de la persona durante este lapso la sesión se cierra (el tablero avisa antes). 0 = nunca.
    idle_timeout: Duration = timedelta(minutes=30)
    cookie_name: str = "minos_session"
    # Intentos fallidos seguidos antes de bloquear la cuenta un rato.
    max_failed_logins: int = 5
    lockout: Duration = timedelta(minutes=15)
    min_password_length: int = 10
    # Primer administrador: se crea al arrancar si todavía no hay ninguna cuenta. Después se puede borrar del .env.
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""


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
    # Zona horaria con la que se agrupan por mes y año las gráficas históricas del análisis general.
    timezone: str = "America/Mexico_City"

    auth: AuthSettings = AuthSettings()
    demo: DemoSettings = DemoSettings()
    ingestion: IngestionSettings = IngestionSettings()
    risk_engine: RiskEngineSettings = RiskEngineSettings()
    connectors: ConnectorSettings = ConnectorSettings()
    notifications: NotificationSettings = NotificationSettings()
    watchlists: WatchlistSettings = WatchlistSettings()

    @property
    def is_development(self) -> bool:
        return self.env.lower() == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
