"""Avisos de alertas fuera del tablero: correo, webhook (Slack, Teams o un sistema propio) y WhatsApp.

El motor de riesgo entrega cada alerta nueva al Notifier, que la manda en segundo plano por los canales configurados.
Un canal que falla solo deja un registro; no detiene a los demás ni al motor."""
import asyncio
import hashlib
import hmac
import json
import logging
import smtplib
import ssl
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime
from email.message import EmailMessage

import httpx

from .config import EmailSettings, NotificationSettings, WebhookSettings, WhatsAppSettings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlertNotice:
    target_id: uuid.UUID
    target_name: str
    at: datetime
    kind: str
    title: str
    message: str
    index: float
    level_label: str
    dashboard_url: str
    mention_url: str | None = None

    @property
    def subject(self) -> str:
        return f"[minOS] {self.title} · {self.target_name}"

    @property
    def text(self) -> str:
        lines = [
            f"{self.title} · {self.target_name}",
            self.message,
            f"Índice actual: {self.index:.1f} / 100 ({self.level_label})",
        ]
        if self.mention_url:
            lines.append(f"Mención: {self.mention_url}")
        lines.append(f"Tablero: {self.dashboard_url}")
        return "\n".join(lines)


class Channel(ABC):
    name: str

    @property
    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    async def send(self, notice: AlertNotice) -> None: ...


class EmailChannel(Channel):
    name = "email"

    def __init__(self, settings: EmailSettings, timeout: float) -> None:
        self._s = settings
        self._timeout = timeout

    @property
    def is_configured(self) -> bool:
        return bool(self._s.host and self._s.from_addr and self._s.to)

    def message(self, notice: AlertNotice) -> EmailMessage:
        msg = EmailMessage()
        msg["Subject"] = notice.subject
        msg["From"] = self._s.from_addr
        msg["To"] = ", ".join(self._s.to)
        msg.set_content(notice.text)
        return msg

    def _send_sync(self, msg: EmailMessage) -> None:
        context = ssl.create_default_context()
        if self._s.port == 465:
            server = smtplib.SMTP_SSL(self._s.host, self._s.port, timeout=self._timeout, context=context)
        else:
            server = smtplib.SMTP(self._s.host, self._s.port, timeout=self._timeout)
        with server:
            if self._s.starttls and self._s.port != 465:
                server.starttls(context=context)
            if self._s.username:
                server.login(self._s.username, self._s.password)
            server.send_message(msg)

    async def send(self, notice: AlertNotice) -> None:
        # smtplib bloquea; corre en un hilo para no detener el ciclo de eventos.
        await asyncio.to_thread(self._send_sync, self.message(notice))


class WebhookChannel(Channel):
    name = "webhook"

    def __init__(self, http: httpx.AsyncClient, settings: WebhookSettings) -> None:
        self._http = http
        self._s = settings

    @property
    def is_configured(self) -> bool:
        return bool(self._s.urls)

    def body(self, notice: AlertNotice) -> bytes:
        alert = asdict(notice) | {"target_id": str(notice.target_id), "at": notice.at.isoformat()}
        return json.dumps({"text": notice.text, "alert": alert}, ensure_ascii=False).encode()

    async def send(self, notice: AlertNotice) -> None:
        body = self.body(notice)
        headers = {"content-type": "application/json"}
        if self._s.secret:
            digest = hmac.new(self._s.secret.encode(), body, hashlib.sha256).hexdigest()
            headers["X-Minos-Signature"] = f"sha256={digest}"
        for url in self._s.urls:
            response = await self._http.post(url, content=body, headers=headers)
            response.raise_for_status()


class WhatsAppChannel(Channel):
    name = "whatsapp"

    def __init__(self, http: httpx.AsyncClient, settings: WhatsAppSettings) -> None:
        self._http = http
        self._s = settings

    @property
    def is_configured(self) -> bool:
        return bool(self._s.access_token and self._s.phone_number_id and self._s.to)

    def payload(self, notice: AlertNotice, to: str) -> dict:
        # Las variables de plantilla no admiten saltos de línea ni más de 4 espacios seguidos.
        params = [notice.target_name, notice.title, f"{notice.message} Índice {notice.index:.0f}/100. {notice.dashboard_url}"]
        return {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": self._s.template,
                "language": {"code": self._s.language},
                "components": [{"type": "body", "parameters": [
                    {"type": "text", "text": " ".join(p.split())[:1000]} for p in params
                ]}],
            },
        }

    async def send(self, notice: AlertNotice) -> None:
        for to in self._s.to:
            response = await self._http.post(
                f"{self._s.graph_url}/{self._s.phone_number_id}/messages", json=self.payload(notice, to),
                headers={"Authorization": f"Bearer {self._s.access_token}"},
            )
            response.raise_for_status()


class Notifier:
    def __init__(self, channels: list[Channel], settings: NotificationSettings) -> None:
        self._all = channels
        self._channels = [c for c in channels if c.is_configured]
        self._settings = settings
        self._tasks: set[asyncio.Task] = set()

    @classmethod
    def from_settings(cls, settings: NotificationSettings, http: httpx.AsyncClient) -> "Notifier":
        timeout = settings.timeout.total_seconds()
        return cls([
            EmailChannel(settings.email, timeout),
            WebhookChannel(http, settings.webhook),
            WhatsAppChannel(http, settings.whatsapp),
        ], settings)

    @property
    def channels(self) -> list[str]:
        return [c.name for c in self._channels]

    @property
    def status(self) -> dict[str, bool]:
        """Todos los canales, configurados o no (panel de fuentes del tablero)."""
        return {c.name: c.is_configured for c in self._all}

    def dashboard_link(self, target_id: uuid.UUID) -> str:
        return f"{self._settings.dashboard_url.rstrip('/')}/?target={target_id}"

    def dispatch(self, notices: list[AlertNotice]) -> None:
        """Manda en segundo plano, para que un servidor lento no frene el recálculo de los demás objetivos."""
        for notice in notices:
            for channel in self._channels:
                task = asyncio.create_task(self._send(channel, notice))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

    async def _send(self, channel: Channel, notice: AlertNotice) -> None:
        try:
            await asyncio.wait_for(channel.send(notice), self._settings.timeout.total_seconds())
            log.info("Aviso por %s: %s", channel.name, notice.subject)
        except Exception as ex:
            log.warning("No se pudo avisar por %s (%s): %s", channel.name, notice.subject, ex or type(ex).__name__)

    async def drain(self) -> None:
        """Espera los envíos pendientes (al detener el proceso y en pruebas)."""
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
