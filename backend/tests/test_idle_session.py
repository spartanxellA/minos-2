"""Cierre de sesión tras 30 min sin actividad: solo cuenta lo que hace la persona, no las consultas automáticas ni
el WebSocket, y cada cierre queda en la auditoría."""
import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from conftest import POSTGRES_URL, migrate, needs_postgres, reset_postgres
from fastapi.testclient import TestClient
from minos import api as api_module
from minos.config import Settings
from minos.main import create_app
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.websockets import WebSocketDisconnect
from test_auth import ADMIN, PASSWORD, login

TARGET = "00000000-0000-0000-0000-000000000001"


def make_settings(request, tmp_path, **auth):
    common = dict(env="development", role="api", auth={
        "mode": "local", "bootstrap_admin_email": ADMIN[0], "bootstrap_admin_password": ADMIN[1], **auth,
    })
    if request.param == "postgres":
        reset_postgres(POSTGRES_URL)
        migrate(POSTGRES_URL)
        return Settings(database_url=POSTGRES_URL, **common)
    return Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'minos.db'}", create_schema=True, **common)


DB = ["sqlite", pytest.param("postgres", marks=needs_postgres)]


@pytest.fixture(params=DB)
def settings(request, tmp_path):
    return make_settings(request, tmp_path)


@pytest.fixture
def app(settings):
    return lambda: create_app(settings)


def _sql(settings, sql: str, **params):
    async def run():
        engine = create_async_engine(settings.database_url)
        async with engine.begin() as conn:
            rows = (await conn.execute(text(sql), params)).all() if sql.lstrip().upper().startswith("SELECT") else \
                (await conn.execute(text(sql), params)) and None
        await engine.dispose()
        return rows

    return asyncio.run(run())


def idle_for(settings, minutes: float) -> None:
    """Simula que la última actividad de todas las sesiones fue hace tantos minutos."""
    _sql(settings, "UPDATE user_sessions SET last_seen_at = :at", at=datetime.now(UTC) - timedelta(minutes=minutes))


def last_seen(settings) -> list[datetime]:
    rows = _sql(settings, "SELECT last_seen_at FROM user_sessions")
    out = []
    for (v,) in rows:
        v = datetime.fromisoformat(v) if isinstance(v, str) else v
        out.append(v if v.tzinfo else v.replace(tzinfo=UTC))
    return out


def idle_events(client):
    r = client.get("/api/audit", params={"action": "auth.idle_timeout"})
    assert r.status_code == 200, r.text
    return r.json()["events"]


def test_me_tells_the_dashboard_the_idle_timeout(app):
    with TestClient(app()) as c:
        assert login(c, *ADMIN).json()["idleTimeoutSeconds"] == 1800
        assert c.get("/api/auth/me").json()["idleTimeoutSeconds"] == 1800


def test_automatic_requests_do_not_keep_the_session_alive(app, settings):
    with TestClient(app()) as c, TestClient(app()) as admin:
        login(c, *ADMIN)
        idle_for(settings, 29)
        before = last_seen(settings)
        assert c.get("/api/targets").status_code == 200  # consulta automática del tablero
        assert last_seen(settings) == before

        idle_for(settings, 31)
        assert c.get("/api/targets").status_code == 401
        assert c.get("/api/targets").status_code == 401
        assert c.get("/api/auth/me").status_code == 401
        assert last_seen(settings) == []  # la sesión se borró

        login(admin, *ADMIN)
        rows = idle_events(admin)
        assert len(rows) == 1  # una sola vez aunque llegaran varias peticiones
        assert rows[0]["actorEmail"] == ADMIN[0] and rows[0]["detail"]["via"] == "server"
        assert rows[0]["actionLabel"] == "Sesión cerrada por inactividad"


def test_activity_from_the_person_resets_the_clock(app, settings):
    with TestClient(app()) as c:
        login(c, *ADMIN)
        idle_for(settings, 29)
        assert c.post("/api/auth/activity").status_code == 204
        assert datetime.now(UTC) - last_seen(settings)[0] < timedelta(seconds=10)
        idle_for(settings, 29)
        assert c.get("/api/auth/me").status_code == 200  # abrir o recargar el tablero también cuenta
        assert datetime.now(UTC) - last_seen(settings)[0] < timedelta(seconds=10)
        assert c.get("/api/targets").status_code == 200


def test_dashboard_closes_the_session_for_inactivity(app):
    with TestClient(app()) as c, TestClient(app()) as admin:
        login(c, *ADMIN)
        assert c.post("/api/auth/logout", json={"reason": "idle"}).status_code == 204
        assert c.get("/api/auth/me").status_code == 401
        login(admin, *ADMIN)
        rows = idle_events(admin)
        assert [r["detail"]["via"] for r in rows] == ["dashboard"]
        assert admin.get("/api/audit", params={"action": "auth.logout"}).json()["events"] == []
        assert admin.post("/api/auth/logout").status_code == 204  # sin cuerpo sigue siendo un cierre normal
        login(admin, *ADMIN)
        assert len(admin.get("/api/audit", params={"action": "auth.logout"}).json()["events"]) == 1


def test_abandoned_sessions_are_closed_and_recorded_on_next_login(app, settings):
    with TestClient(app()) as gone, TestClient(app()) as admin:
        login(admin, *ADMIN)
        admin.post("/api/users", json={"email": "lector@minos.mx", "role": "viewer", "password": PASSWORD})
        login(gone, "lector@minos.mx", PASSWORD)
        idle_for(settings, 45)  # nadie volvió a usar esas pestañas
        login(admin, *ADMIN)
        rows = idle_events(admin)
        assert {(r["actorEmail"], r["detail"]["via"]) for r in rows} == {
            ("lector@minos.mx", "cleanup"), (ADMIN[0], "cleanup"),
        }
        assert gone.get("/api/targets").status_code == 401


def test_websocket_is_closed_when_the_session_goes_idle(app, settings, monkeypatch):
    monkeypatch.setattr(api_module, "WS_SESSION_CHECK", 0)
    with TestClient(app()) as c:
        login(c, *ADMIN)
        with c.websocket_connect(f"/ws/targets/{TARGET}") as ws:
            ws.send_text("ping")  # los pings no cuentan como actividad
            idle_for(settings, 31)
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.send_text("ping")
                ws.receive_text()
        assert closed.value.code == 1008


@pytest.fixture(params=DB)
def no_idle(request, tmp_path):
    return make_settings(request, tmp_path, idle_timeout=0)


def test_zero_turns_the_idle_timeout_off(no_idle):
    with TestClient(create_app(no_idle)) as c:
        assert login(c, *ADMIN).json()["idleTimeoutSeconds"] is None
        idle_for(no_idle, 600)
        assert c.get("/api/targets").status_code == 200
