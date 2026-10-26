"""Contrato de una fuente. El conector solo trae y normaliza datos; el análisis ocurre después, una sola vez."""
import re
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from ..domain.mentions import MentionDraft
from ..domain.targets import MonitoredTarget

USER_AGENT = "minOS/2.0 (+monitoreo de reputacion)"  # los encabezados HTTP solo admiten ASCII


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
