import random
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from ..config import DemoSettings
from ..domain.mentions import AuthorInfo, Engagement, MentionDraft
from ..domain.targets import MonitoredTarget
from .base import ConnectorCursor, MentionConnector

TEMPLATES = [
    "Gran trabajo de {0} con el nuevo programa, un logro para todos",
    "{0} presentó su informe anual; avance en transparencia según analistas",
    "Reunión de {0} con empresarios de la región esta mañana",
    "Críticas a {0} por la falta de respuesta ante la crisis del agua",
    "Denuncia ciudadana señala negligencia de {0} en la obra pública",
    "Columnistas piden investigacion sobre contratos firmados por {0}",
    "Acusan a {0} de corrupcion en licitaciones, piden su renuncia",
    "{0} anuncia apoyo a pequeños productores; reconocimiento de cámaras",
    "Opinión: lo que {0} no ha explicado sobre su patrimonio",
]

AUTHORS = [
    ("@noticias_mx", 2_400_000), ("@columnista", 180_000), ("@ciudadano_42", 310), ("@observatorio", 52_000),
    ("@reportera", 95_000), ("@vecino_tlalpan", 1_200), ("@radio_fm", 640_000),
]


class DemoConnector(MentionConnector):
    """Fuente sintética para demostraciones: unas pocas menciones de plantillas en cada ronda."""

    source = "demo"

    def __init__(self, settings: DemoSettings) -> None:
        self._settings = settings

    @property
    def poll_interval(self) -> timedelta:
        return self._settings.poll_interval

    @property
    def is_configured(self) -> bool:
        return self._settings.enabled

    async def fetch(self, target: MonitoredTarget, cursor: ConnectorCursor) -> AsyncIterator[MentionDraft]:
        now = datetime.now(UTC)
        for _ in range(random.randint(1, 5)):
            handle, followers = random.choice(AUTHORS)
            mid = uuid.uuid4().hex
            yield MentionDraft(
                source=self.source,
                external_id=mid,
                url=f"https://example.org/demo/{mid}",
                author=AuthorInfo(handle, handle.lstrip("@"), followers),
                published_at=now - timedelta(seconds=random.randint(0, 59)),
                text=random.choice(TEMPLATES).format(target.name) + f" #{random.randint(0, 999)}",
                language="es",
                engagement=Engagement(random.randint(0, 1999), random.randint(0, 499), random.randint(0, 299)),
            )
        cursor.value = now.isoformat()
