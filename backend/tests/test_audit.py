"""Bitácora de auditoría: qué se registra, con qué datos, y que solo la vean los administradores."""
import asyncio

from fastapi.testclient import TestClient
from test_auth import ADMIN, PASSWORD, app, login, settings  # noqa: F401  (fixtures)

from minos import users as users_cli
from minos.audit import diff
from minos.main import create_app

UA = {"user-agent": "pruebas/1.0"}


def events(client, **params):
    r = client.get("/api/audit", params=params)
    assert r.status_code == 200, r.text
    return r.json()["events"]


def by_action(rows):
    return {e["action"]: e for e in reversed(rows)}  # el más reciente gana


def test_diff_lists_only_changed_fields():
    assert diff({"a": 1, "b": [1], "c": None}, {"a": 1, "b": [2], "d": 3}) == {"b": [[1], [2]], "d": [None, 3]}


def test_logins_failures_and_lockout_are_recorded(app):
    victim = "analista@minos.mx"
    with TestClient(app(), headers=UA) as admin, TestClient(app()) as other:
        login(admin, *ADMIN)
        admin.post("/api/users", json={"email": victim, "role": "analyst", "password": PASSWORD})
        assert login(other, "nadie@minos.mx", "x").status_code == 401
        for _ in range(3):
            login(other, victim, "mala")
        assert login(other, victim, PASSWORD).status_code == 429

        rows = events(admin)
        first_login = events(admin, action="auth.login")[-1]
        assert first_login["success"] and first_login["actorEmail"] == ADMIN[0] and first_login["actorRole"] == "admin"
        assert first_login["ip"] == "testclient" and first_login["userAgent"] == "pruebas/1.0"
        failed = [e for e in rows if e["action"] == "auth.login_failed"]
        reasons = [e["detail"]["reason"] for e in failed]
        assert reasons.count("wrong_password") == 3 and "unknown_account" in reasons and "locked" in reasons
        assert all(not e["success"] and e["actorId"] is None for e in failed)
        assert any(e["action"] == "auth.locked" and e["entityLabel"] == victim for e in rows)
        # Nunca se guarda la contraseña que se escribió.
        assert "mala" not in admin.get("/api/audit/export.csv").text

        assert [e["action"] for e in events(admin, success="false", action="auth.")][:1] == ["auth.login_failed"]
        assert all(e["detail"]["reason"] == "unknown_account" for e in events(admin, q="nadie@"))


def test_account_changes_keep_before_and_after(app):
    with TestClient(app()) as admin, TestClient(app()) as viewer:
        login(admin, *ADMIN)
        user = admin.post("/api/users", json={"email": "lector@minos.mx", "name": "Lectora", "role": "viewer",
                                              "password": PASSWORD}).json()
        admin.patch(f"/api/users/{user['id']}", json={"role": "analyst", "name": "Lectora 2"})
        admin.patch(f"/api/users/{user['id']}", json={"password": PASSWORD + "x"})
        admin.patch(f"/api/users/{user['id']}", json={"role": "analyst"})  # sin cambios: no se registra
        admin.delete(f"/api/users/{user['id']}")

        rows = events(admin, entityId=user["id"])
        assert [e["action"] for e in rows] == ["user.deleted", "user.updated", "user.updated", "user.created"]
        deleted, reset, changed, created = rows
        assert created["changes"]["role"] == [None, "viewer"] and created["actorEmail"] == ADMIN[0]
        assert changed["changes"] == {"name": ["Lectora", "Lectora 2"], "role": ["viewer", "analyst"]}
        assert reset["changes"] is None and reset["detail"] == {"passwordReset": True}
        assert deleted["changes"]["email"] == ["lector@minos.mx", None]
        assert PASSWORD not in admin.get("/api/audit/export.csv").text

        # Solo los administradores ven la bitácora.
        admin.post("/api/users", json={"email": "l2@minos.mx", "role": "analyst", "password": PASSWORD})
        login(viewer, "l2@minos.mx", PASSWORD)
        assert viewer.get("/api/audit").status_code == 403
        assert viewer.get("/api/audit/export.csv").status_code == 403


def test_targets_and_surveys_are_recorded(app):
    with TestClient(app()) as c:
        login(c, *ADMIN)
        t = c.post("/api/targets", json={"name": "Acme", "kind": "Company", "keywords": ["acme"]}).json()
        c.put(f"/api/targets/{t['id']}", json={"name": "Acme SA", "kind": "Company", "keywords": ["acme", "=cmd"]})
        survey = c.get("/api/surveys/RASurvey").json()
        answers = {q["id"]: max(q["options"], key=lambda o: o["weight"])["value"] for s in survey["sections"] for q in s["questions"]}
        assert c.post(f"/api/targets/{t['id']}/survey-responses", json={"surveyId": "RASurvey", "answers": answers}).status_code == 200
        assert c.delete(f"/api/targets/{t['id']}").status_code == 204

        rows = by_action(events(c, entityType="target"))
        assert rows["target.created"]["changes"]["name"] == [None, "Acme"]
        assert rows["target.updated"]["changes"] == {"name": ["Acme", "Acme SA"], "keywords": [["acme"], ["acme", "=cmd"]]}
        assert rows["survey.submitted"]["detail"]["surveyId"] == "RASurvey"
        assert rows["survey.submitted"]["detail"]["level"] == "High"
        assert rows["target.deleted"]["entityLabel"] == "Acme SA"  # el registro sobrevive al objetivo

        csv = c.get("/api/audit/export.csv", params={"entityType": "target"})
        assert csv.headers["content-type"].startswith("text/csv")
        assert "attachment" in csv.headers["content-disposition"]
        assert csv.text.count("\n") == 5  # encabezado + 4 eventos
        assert events(c)[0]["action"] == "audit.exported"


def test_pages_go_back_in_time(app):
    with TestClient(app()) as c:
        login(c, *ADMIN)
        for i in range(5):
            c.post("/api/targets", json={"name": f"T{i}"})
        first = c.get("/api/audit", params={"limit": 3, "action": "target.created"}).json()
        assert [e["entityLabel"] for e in first["events"]] == ["T4", "T3", "T2"]
        second = c.get("/api/audit", params={"limit": 3, "action": "target.created", "before": first["nextBefore"]}).json()
        assert [e["entityLabel"] for e in second["events"]] == ["T1", "T0"] and second["nextBefore"] is None
        assert first["actions"]["target.created"] == "Objetivo creado"


def test_bootstrap_and_terminal_are_recorded_as_system(settings, monkeypatch):  # noqa: F811
    with TestClient(create_app(settings)):
        pass
    monkeypatch.setattr(users_cli, "get_settings", lambda: settings)
    monkeypatch.setenv("MINOS_NEW_PASSWORD", PASSWORD)
    asyncio.run(users_cli.main(["add", "cli@minos.mx", "--role", "analyst"]))
    asyncio.run(users_cli.main(["password", "cli@minos.mx"]))
    with TestClient(create_app(settings)) as c:
        login(c, *ADMIN)
        rows = events(c, actor="sistema")
        assert [(e["action"], e["entityLabel"]) for e in rows] == [
            ("user.updated", "cli@minos.mx"), ("user.created", "cli@minos.mx"), ("user.created", ADMIN[0]),
        ]
        assert rows[0]["detail"]["passwordReset"] and "terminal" in rows[0]["detail"]["via"]
