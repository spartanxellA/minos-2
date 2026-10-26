"""Avisos de alertas: formato de cada canal y que un canal caído no afecte a los demás."""
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime

import httpx
from test_connectors import stub

from minos import notifications
from minos.config import EmailSettings, NotificationSettings, WebhookSettings, WhatsAppSettings
from minos.notifications import AlertNotice, Channel, EmailChannel, Notifier, WebhookChannel, WhatsAppChannel

NOTICE = AlertNotice(
    target_id=uuid.UUID(int=1), target_name="Ana López", at=datetime(2026, 10, 25, 18, tzinfo=UTC),
    kind="SevereHighReachMention", title="Acusación de alto alcance",
    message="@diario (120,000 seguidores) en x: Denuncian fraude", index=62.34, level_label="Riesgo alto",
    dashboard_url="https://minos.example/?target=00000000-0000-0000-0000-000000000001",
    mention_url="https://x.com/diario/status/1",
)


def test_notice_text_has_what_to_do_next():
    assert NOTICE.subject == "[minOS] Acusación de alto alcance · Ana López"
    assert NOTICE.text.splitlines() == [
        "Acusación de alto alcance · Ana López",
        "@diario (120,000 seguidores) en x: Denuncian fraude",
        "Índice actual: 62.3 / 100 (Riesgo alto)",
        "Mención: https://x.com/diario/status/1",
        "Tablero: https://minos.example/?target=00000000-0000-0000-0000-000000000001",
    ]


async def test_webhook_posts_slack_compatible_json_signed_with_hmac():
    http, requests = stub(lambda r: httpx.Response(200))
    channel = WebhookChannel(http, WebhookSettings(urls=["https://hooks.example/a", "https://hooks.example/b"], secret="s3"))

    await channel.send(NOTICE)

    assert [str(r.url) for r in requests] == ["https://hooks.example/a", "https://hooks.example/b"]
    body = requests[0].content
    payload = json.loads(body)
    assert payload["text"] == NOTICE.text
    assert payload["alert"]["target_name"] == "Ana López"
    assert payload["alert"]["target_id"] == str(NOTICE.target_id)
    expected = hmac.new(b"s3", body, hashlib.sha256).hexdigest()
    assert requests[0].headers["x-minos-signature"] == f"sha256={expected}"


async def test_whatsapp_sends_the_approved_template_to_each_number():
    http, requests = stub(lambda r: httpx.Response(200, json={"messages": [{"id": "wamid"}]}))
    channel = WhatsAppChannel(http, WhatsAppSettings(access_token="tok", phone_number_id="123", to=["5215511111111", "5215522222222"]))

    await channel.send(NOTICE)

    assert len(requests) == 2
    assert str(requests[0].url) == "https://graph.facebook.com/v23.0/123/messages"
    assert requests[0].headers["authorization"] == "Bearer tok"
    sent = json.loads(requests[1].content)
    assert sent["to"] == "5215522222222"
    assert sent["template"]["name"] == "minos_alerta"
    params = [p["text"] for p in sent["template"]["components"][0]["parameters"]]
    assert params[:2] == ["Ana López", "Acusación de alto alcance"]
    assert "\n" not in params[2] and "Índice 62/100" in params[2]


async def test_email_uses_starttls_login_and_sends_to_every_recipient(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            sent["server"] = (host, port)
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False
        def starttls(self, context):
            sent["tls"] = True
        def login(self, user, password):
            sent["login"] = user
        def send_message(self, msg):
            sent["msg"] = msg

    monkeypatch.setattr(notifications.smtplib, "SMTP", FakeSMTP)
    channel = EmailChannel(EmailSettings(host="smtp.example", username="u", password="p", from_addr="minos@example.com",
                                         to=["a@example.com", "b@example.com"]), timeout=5)

    await channel.send(NOTICE)

    assert sent["server"] == ("smtp.example", 587)
    assert sent["tls"] and sent["login"] == "u"
    assert sent["msg"]["To"] == "a@example.com, b@example.com"
    assert sent["msg"]["Subject"] == NOTICE.subject
    assert "Índice actual: 62.3" in sent["msg"].get_content()


class Recorder(Channel):
    name = "recorder"
    is_configured = True

    def __init__(self, fail=False):
        self.fail = fail
        self.got: list[AlertNotice] = []

    async def send(self, notice):
        if self.fail:
            raise RuntimeError("caído")
        self.got.append(notice)


async def test_a_failing_channel_does_not_stop_the_others(caplog):
    ok = Recorder()
    notifier = Notifier([Recorder(fail=True), ok], NotificationSettings())

    notifier.dispatch([NOTICE])
    await notifier.drain()

    assert ok.got == [NOTICE]
    assert "No se pudo avisar por recorder" in caplog.text


def test_unconfigured_channels_are_left_out():
    notifier = Notifier.from_settings(NotificationSettings(webhook=WebhookSettings(urls=["https://h"])), httpx.AsyncClient())
    assert notifier.channels == ["webhook"]
    assert notifier.dashboard_link(uuid.UUID(int=1)) == "http://localhost:3000/?target=00000000-0000-0000-0000-000000000001"


async def test_email_on_port_465_uses_implicit_tls(monkeypatch):
    used = []

    class FakeSSL:
        def __init__(self, host, port, timeout, context):
            used.append(port)
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False
        def send_message(self, msg):
            pass

    monkeypatch.setattr(notifications.smtplib, "SMTP_SSL", FakeSSL)
    await EmailChannel(EmailSettings(host="h", port=465, from_addr="f@x", to=["t@x"]), 5).send(NOTICE)
    assert used == [465]
