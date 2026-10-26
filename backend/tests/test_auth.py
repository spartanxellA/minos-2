"""Inicio de sesión, roles, bloqueo por intentos, origen y administración de cuentas."""
import asyncio

import pytest
from conftest import POSTGRES_URL, migrate, needs_postgres, reset_postgres
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from minos import users as users_cli
from minos.auth import hash_password, verify_password
from minos.main import create_app
from minos.config import Settings

ADMIN = ("admin@minos.mx", "contraseña-admin-1")
PASSWORD = "contraseña-segura"


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=needs_postgres)])
def settings(request, tmp_path):
    common = dict(env="development", role="api", auth={
        "mode": "local", "bootstrap_admin_email": ADMIN[0], "bootstrap_admin_password": ADMIN[1],
        "max_failed_logins": 3,
    })
    if request.param == "postgres":
        reset_postgres(POSTGRES_URL)
        migrate(POSTGRES_URL)
        return Settings(database_url=POSTGRES_URL, **common)
    return Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'minos.db'}", create_schema=True, **common)


@pytest.fixture
def app(settings):
    """Una app por cliente: cada TestClient corre en su propio ciclo de eventos y asyncpg no comparte conexiones
    entre ciclos. Todas usan la misma base."""
    return lambda: create_app(settings)


def login(client, email, password):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_password_hash_roundtrip():
    stored = hash_password("abc12345678")
    assert stored.startswith("scrypt$") and "abc" not in stored
    assert verify_password("abc12345678", stored)
    assert not verify_password("otra", stored)
    assert not verify_password("abc12345678", "basura")


def test_everything_needs_a_session(app):
    with TestClient(app()) as c:
        assert c.get("/health").status_code == 200
        assert c.get("/api/targets").status_code == 401
        assert c.get("/api/auth/me").status_code == 401
        with pytest.raises(WebSocketDisconnect) as closed, c.websocket_connect("/ws/targets/00000000-0000-0000-0000-000000000001") as ws:
            ws.receive_text()
        assert closed.value.code == 1008


def test_bootstrap_admin_logs_in_and_out(app):
    with TestClient(app()) as c:
        r = login(c, ADMIN[0].upper(), ADMIN[1])  # el correo no distingue mayúsculas
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "admin"
        cookie = r.headers["set-cookie"]
        assert "minos_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
        assert c.get("/api/auth/me").json()["email"] == ADMIN[0]
        assert c.get("/api/targets").status_code == 200

        assert c.post("/api/auth/logout").status_code == 204
        assert c.get("/api/targets").status_code == 401


def test_roles_limit_what_each_account_can_do(app):
    with TestClient(app()) as admin, TestClient(app()) as viewer, TestClient(app()) as analyst:
        login(admin, *ADMIN)
        for email, role in (("lector@minos.mx", "viewer"), ("analista@minos.mx", "analyst")):
            r = admin.post("/api/users", json={"email": email, "name": role, "role": role, "password": PASSWORD})
            assert r.status_code == 201, r.text
        login(viewer, "lector@minos.mx", PASSWORD)
        login(analyst, "analista@minos.mx", PASSWORD)

        body = {"name": "Ana López", "kind": "Person"}
        assert viewer.post("/api/targets", json=body).status_code == 403
        t = analyst.post("/api/targets", json=body).json()
        assert viewer.get(f"/api/targets/{t['id']}").status_code == 200
        assert viewer.post(f"/api/targets/{t['id']}/survey-responses", json={"surveyId": "PDSurvey", "answers": {}}).status_code == 403
        assert analyst.post(f"/api/targets/{t['id']}/survey-responses", json={"surveyId": "PDSurvey", "answers": {}}).status_code == 200
        assert analyst.delete(f"/api/targets/{t['id']}").status_code == 403
        assert analyst.get("/api/users").status_code == 403
        assert admin.delete(f"/api/targets/{t['id']}").status_code == 204

        with viewer.websocket_connect(f"/ws/targets/{t['id']}"):
            pass  # el lector sí ve en vivo


def test_repeated_failures_lock_the_account(app):
    with TestClient(app()) as c:
        for _ in range(3):
            assert login(c, ADMIN[0], "mal").status_code == 401
        r = login(c, *ADMIN)
        assert r.status_code == 429
        assert "Vuelve a intentar" in r.json()["detail"]
        assert login(c, "nadie@minos.mx", "mal").status_code == 401  # mismo mensaje que una contraseña mala


def test_requests_from_another_site_are_rejected(app):
    with TestClient(app()) as c:
        login(c, *ADMIN)
        evil = {"origin": "https://otro-sitio.example"}
        assert c.post("/api/targets", json={"name": "X"}, headers=evil).status_code == 403
        assert c.get("/api/targets", headers=evil).status_code == 200  # leer no cambia nada; CORS decide si se ve
        assert c.post("/api/targets", json={"name": "X"}, headers={"origin": "http://localhost:3000"}).status_code == 201
        with pytest.raises(WebSocketDisconnect), c.websocket_connect("/ws/targets/00000000-0000-0000-0000-000000000001", headers=evil) as ws:
            ws.receive_text()


def test_deactivating_or_resetting_ends_sessions_and_one_admin_must_remain(app):
    with TestClient(app()) as admin, TestClient(app()) as other:
        me = login(admin, *ADMIN).json()
        u = admin.post("/api/users", json={"email": "x@minos.mx", "password": PASSWORD}).json()
        assert u["role"] == "viewer"
        assert admin.post("/api/users", json={"email": "X@minos.mx", "password": PASSWORD}).status_code == 409
        assert admin.post("/api/users", json={"email": "y@minos.mx", "password": "corta"}).status_code == 422

        login(other, "x@minos.mx", PASSWORD)
        assert other.get("/api/targets").status_code == 200
        admin.patch(f"/api/users/{u['id']}", json={"active": False})
        assert other.get("/api/targets").status_code == 401
        assert login(other, "x@minos.mx", PASSWORD).status_code == 401

        assert admin.patch(f"/api/users/{me['id']}", json={"role": "viewer"}).status_code == 409
        assert admin.delete(f"/api/users/{me['id']}").status_code == 409
        assert admin.delete(f"/api/users/{u['id']}").status_code == 204
        assert [x["email"] for x in admin.get("/api/users").json()] == [ADMIN[0]]


def test_changing_password_keeps_this_session_and_closes_the_others(app):
    with TestClient(app()) as here, TestClient(app()) as elsewhere:
        login(here, *ADMIN)
        login(elsewhere, *ADMIN)
        assert here.post("/api/auth/password", json={"currentPassword": "mal", "newPassword": PASSWORD}).status_code == 400
        assert here.post("/api/auth/password", json={"currentPassword": ADMIN[1], "newPassword": PASSWORD}).status_code == 204
        assert here.get("/api/auth/me").status_code == 200
        assert elsewhere.get("/api/auth/me").status_code == 401
        assert login(elsewhere, ADMIN[0], PASSWORD).status_code == 200


def test_cli_creates_accounts_and_resets_passwords(settings, monkeypatch, capsys):
    with TestClient(create_app(settings)):
        pass  # crea el esquema (SQLite) o usa el migrado
    monkeypatch.setattr(users_cli, "get_settings", lambda: settings)
    monkeypatch.setenv("MINOS_NEW_PASSWORD", PASSWORD)
    asyncio.run(users_cli.main(["add", "Nueva@Minos.mx", "--role", "analyst", "--name", "Nueva"]))
    asyncio.run(users_cli.main(["password", ADMIN[0]]))
    asyncio.run(users_cli.main(["list"]))
    out = capsys.readouterr().out
    assert "Cuenta creada: nueva@minos.mx (analyst)" in out
    assert "nueva@minos.mx\tanalyst\tactiva\tNueva" in out
    with TestClient(create_app(settings)) as c:
        assert login(c, ADMIN[0], PASSWORD).status_code == 200


def test_auth_off_is_refused_outside_development():
    with pytest.raises(RuntimeError, match="MINOS_AUTH__MODE=off"):
        create_app(Settings(env="production", auth={"mode": "off"}))
