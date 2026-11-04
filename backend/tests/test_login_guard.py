"""Protección del inicio de sesión: límites por correo + IP, por correo y por IP, sin revelar qué correos existen."""
import pytest
from fastapi.testclient import TestClient

from minos import runtime
from minos.bus import MemoryBus
from minos.config import Settings
from minos.main import create_app

ADMIN = ("admin@minos.mx", "contraseña-admin-1")


@pytest.fixture
def shared_bus(monkeypatch):
    """Un solo bus para todas las apps de la prueba, como el Redis que comparten las réplicas de la API."""
    bus = MemoryBus()
    monkeypatch.setattr(runtime, "create_bus", lambda url: bus)
    return bus


@pytest.fixture
def client(tmp_path, shared_bus):
    settings = Settings(
        env="development", role="api", database_url=f"sqlite+aiosqlite:///{tmp_path / 'minos.db'}", create_schema=True,
        auth={"mode": "local", "bootstrap_admin_email": ADMIN[0], "bootstrap_admin_password": ADMIN[1],
              "max_failed_logins": 3, "account_max_failed_logins": 5, "ip_max_failed_logins": 6},
    )
    return lambda ip="10.0.0.1": TestClient(create_app(settings), client=(ip, 50000))


def login(c, email, password):
    return c.post("/api/auth/login", json={"email": email, "password": password})


class FakeNotifier:
    channels = ["email"]
    home_link = "https://minos.example/"

    def __init__(self):
        self.sent = []

    def dispatch(self, notices):
        self.sent.extend(notices)

    async def drain(self):
        return None


def audit_actions(admin):
    return [e["action"] for e in admin.get("/api/audit", params={"limit": 200}).json()["events"]]


def test_unknown_and_real_emails_lock_the_same_way(client):
    """Antes solo se bloqueaban los correos con cuenta, y el 429 delataba cuáles existían."""
    with client() as c:
        answers = {}
        for email in (ADMIN[0], "nadie@minos.mx"):
            codes = [login(c, email, "mal").status_code for _ in range(3)]
            r = login(c, email, "mal")
            answers[email] = (codes, r.status_code, r.json()["detail"], "retry-after" in r.headers)
        assert answers[ADMIN[0]] == answers["nadie@minos.mx"]
        codes, status, detail, retry_after = answers[ADMIN[0]]
        assert codes == [401, 401, 401] and status == 429 and retry_after
        assert detail == "Demasiados intentos. Vuelve a intentar en 15 min."


def test_a_lock_from_one_ip_does_not_shut_out_the_owner(client):
    """Quien adivina desde su IP queda fuera, pero no puede dejar sin acceso a la persona dueña de la cuenta."""
    with client("203.0.113.9") as attacker, client("10.0.0.1") as owner:
        for _ in range(3):
            assert login(attacker, ADMIN[0], "mal").status_code == 401
        assert login(attacker, *ADMIN).status_code == 429  # ni con la contraseña correcta
        assert login(owner, *ADMIN).status_code == 200


def test_one_ip_trying_many_emails_gets_blocked(client):
    with client("203.0.113.9") as c, client("10.0.0.1") as admin:
        codes = [login(c, f"persona{i}@minos.mx", "mal").status_code for i in range(6)]
        assert codes == [401] * 6
        r = login(c, *ADMIN)
        assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
        assert login(admin, *ADMIN).status_code == 200  # otra IP sigue entrando
        actions = audit_actions(admin)
        assert "auth.ip_blocked" in actions
        failed = admin.get("/api/audit", params={"action": "auth.login_failed", "limit": 1}).json()["events"][0]
        assert failed["detail"]["reason"] == "ip_blocked"


def test_an_attack_spread_over_many_ips_locks_the_email_and_alerts(client):
    with client("10.0.0.1") as admin:
        assert login(admin, *ADMIN).status_code == 200
        notifier = FakeNotifier()
        admin.app.state.runtime.notifier = notifier
        target = "analista@minos.mx"
        for i in range(5):
            with client(f"198.51.100.{i}") as bot:
                bot.app.state.runtime.notifier = notifier
                assert login(bot, target, "mal").status_code == 401
        with client("198.51.100.99") as fresh:
            assert login(fresh, target, "mal").status_code == 429
        assert [n.kind for n in notifier.sent] == ["login.account"]
        assert target in notifier.sent[0].message and "198.51.100.4" in notifier.sent[0].message
        lock = admin.get("/api/audit", params={"action": "auth.locked", "limit": 1}).json()["events"][0]
        assert lock["detail"]["scope"] == "account"


def test_resetting_the_password_unlocks_the_account(client):
    with client("10.0.0.1") as admin, client("203.0.113.9") as person:
        login(admin, *ADMIN)
        r = admin.post("/api/users", json={"email": "lector@minos.mx", "name": "L", "role": "viewer",
                                           "password": "contraseña-segura"})
        user_id = r.json()["id"]
        for _ in range(3):
            login(person, "lector@minos.mx", "mal")
        assert login(person, "lector@minos.mx", "contraseña-segura").status_code == 429
        assert admin.patch(f"/api/users/{user_id}", json={"password": "otra-contraseña-1"}).status_code == 200
        assert login(person, "lector@minos.mx", "otra-contraseña-1").status_code == 200


def test_a_successful_login_clears_the_failures_from_that_ip(client):
    with client() as c:
        for _ in range(2):
            login(c, ADMIN[0], "mal")
        assert login(c, *ADMIN).status_code == 200
        for _ in range(2):
            assert login(c, ADMIN[0], "mal").status_code == 401
        assert login(c, *ADMIN).status_code == 200
