"""Contrato de una fuente. El conector solo trae y normaliza datos; el análisis ocurre después, una sola vez."""
import logging
import os
import re
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from ..domain.mentions import MentionDraft
from ..domain.targets import MonitoredTarget

USER_AGENT = "minOS/2.0 (+monitoreo de reputacion)"  # los encabezados HTTP solo admiten ASCII
log = logging.getLogger(__name__)


# Meta y YouTube llevan la llave en la URL, y httpx copia la URL al mensaje de error.
_SECRET_PARAM = re.compile(r"((?:access_token|api_key|key|token|client_secret)=)[^&\s'\"]+", re.IGNORECASE)


def redact_secrets(text: str) -> str:
    """Quita llaves y tokens de un mensaje de error antes de guardarlo o mostrarlo."""
    return _SECRET_PARAM.sub(r"\1***", text)


class ConnectorMode(StrEnum):
    POLL = "poll"  # consulta cada cierto tiempo con un cursor
    STREAM = "stream"  # recibe en tiempo real


@dataclass
class ConnectorCursor:
    """Posición guardada por objetivo y fuente para retomar sin perder ni duplicar."""

    value: str | None = None
    #: Problemas parciales (un feed que no se pudo leer) que no detienen la ronda pero se muestran en «Fuentes».
    warnings: list[str] = field(default_factory=list)


#: Prefijo de last_error cuando la ronda sirvió y solo quedaron avisos (un feed en pausa), no un error de la fuente.
WARNING_PREFIX = "Aviso: "


def join_warnings(warnings: list[str]) -> str | None:
    """Avisos de una ronda como last_error: sin repetidos, uno por línea y con el prefijo de aviso."""
    text = "\n".join(dict.fromkeys(warnings))
    return f"{WARNING_PREFIX}{text}"[:2000] if text else None


def split_warnings(error: str) -> list[str] | None:
    """Los avisos guardados en last_error, o None si es un error de verdad."""
    if not error.startswith(WARNING_PREFIX):
        return None
    return [w for w in error.removeprefix(WARNING_PREFIX).splitlines() if w.strip()]


class MentionConnector(ABC):
    #: Identificador corto de la fuente: "rss", "x", "youtube", "bluesky".
    source: str
    mode: ConnectorMode = ConnectorMode.POLL

    @property
    @abstractmethod
    def poll_interval(self) -> timedelta:
        """Intervalo mínimo entre consultas, para respetar la cuota de la API."""

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """Falso si falta configuración (token, llave), para no intentar conectarse."""

    @abstractmethod
    def fetch(self, target: MonitoredTarget, cursor: ConnectorCursor) -> AsyncIterator[MentionDraft]:
        """Trae menciones nuevas desde la posición del cursor y actualiza cursor.value al avanzar."""

    @property
    def paused_until(self) -> datetime | None:
        """Si la fuente entera está en pausa (sin créditos, cuota agotada), hasta cuándo. None = disponible."""
        return None

    def plan_round(self, active_targets: int) -> None:
        """Se llama al inicio de cada ronda con el número de objetivos activos (para repartir cuotas)."""


class SourceUnavailable(httpx.HTTPError):
    """La fuente pidió esperar o rechazó el acceso; el mensaje explica qué hacer y hasta cuándo se pausa."""


# Cuánto esperar según la respuesta, cuando la fuente no lo dice (Retry-After): base que se duplica en cada
# fallo seguido, con tope.
_PAUSE_POLICY: dict[int, tuple[timedelta, timedelta]] = {
    429: (timedelta(minutes=15), timedelta(hours=6)),   # demasiadas consultas
    503: (timedelta(minutes=10), timedelta(hours=2)),   # servicio saturado
    402: (timedelta(hours=6), timedelta(hours=24)),     # plan vencido o sin créditos: no se arregla solo
    401: (timedelta(hours=1), timedelta(hours=24)),     # llave inválida
    403: (timedelta(hours=1), timedelta(hours=24)),     # acceso bloqueado
    404: (timedelta(hours=12), timedelta(hours=24)),    # el feed ya no existe
    410: (timedelta(hours=24), timedelta(hours=24)),
}

PAUSE_HINTS = {
    429: "demasiadas consultas; se espera lo que pida la fuente",
    503: "la fuente está saturada",
    402: "la fuente pide pago (plan vencido o sin créditos)",
    401: "la llave o el token no son válidos",
    403: "la fuente rechaza el acceso",
    404: "la dirección ya no existe",
    410: "la dirección ya no existe",
}


def retry_after(response: httpx.Response, now: datetime | None = None) -> timedelta | None:
    """Espera pedida por la fuente: Retry-After (segundos o fecha HTTP) o x-rate-limit-reset (época, X)."""
    now = now or datetime.now(UTC)
    value = response.headers.get("retry-after", "").strip()
    if value:
        if value.isdigit():
            return timedelta(seconds=int(value))
        try:
            when = parsedate_to_datetime(value)
            return max(when - now, timedelta(0)) if when.tzinfo else None
        except (TypeError, ValueError):
            pass
    reset = response.headers.get("x-rate-limit-reset", "").strip()
    if reset.isdigit():
        return max(datetime.fromtimestamp(int(reset), UTC) - now, timedelta(0))
    return None


class Backoff:
    """Pausas por clave (un feed, un sitio o un conector entero) tras respuestas 4xx/429, en memoria del worker."""

    def __init__(self) -> None:
        self._until: dict[str, datetime] = {}
        self._failures: dict[str, int] = {}

    def paused_until(self, key: str, now: datetime | None = None) -> datetime | None:
        until = self._until.get(key)
        if until and until > (now or datetime.now(UTC)):
            return until
        return None

    def ok(self, key: str) -> None:
        self._until.pop(key, None)
        self._failures.pop(key, None)

    def pause(self, key: str, response: httpx.Response, now: datetime | None = None) -> datetime | None:
        """Registra el fallo y devuelve hasta cuándo queda en pausa, o None si el código no amerita pausa."""
        policy = _PAUSE_POLICY.get(response.status_code)
        if policy is None:
            return None
        now = now or datetime.now(UTC)
        base, cap = policy
        failures = self._failures.get(key, 0) + 1
        self._failures[key] = failures
        wait = retry_after(response, now)
        if wait is None:
            wait = min(base * 2 ** (failures - 1), cap)
        wait = min(max(wait, timedelta(seconds=30)), timedelta(hours=24))
        self._until[key] = now + wait
        return self._until[key]

    def pause_until(self, key: str, until: datetime) -> datetime:
        self._failures[key] = self._failures.get(key, 0) + 1
        self._until[key] = until
        return until


def parse_since(value: str | None, default_days: int = 2) -> datetime:
    """Fecha guardada en el cursor, o hace `default_days` días si no hay cursor."""
    if value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(UTC) - timedelta(days=default_days)


def parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def local_time(when: datetime) -> str:
    """Hora legible en la zona del tablero (MINOS_TIMEZONE), para los mensajes de pausa."""
    try:
        tz = ZoneInfo(os.environ.get("MINOS_TIMEZONE") or "America/Mexico_City")
    except (ZoneInfoNotFoundError, ValueError):
        tz = UTC
    local = when.astimezone(tz)
    today = datetime.now(tz).date()
    return local.strftime("%H:%M") if local.date() == today else local.strftime("%d/%m %H:%M")
