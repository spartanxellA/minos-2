"""Mantenimiento de objetivos: cambios, baja lógica, reactivación y borrado definitivo."""
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from minos import db
from test_auth import ADMIN, PASSWORD, app, login, settings  # noqa: F401  (fixtures)

PEP = "ANA LOPEZ RUIZ|DIRECTORA|SECRETARIA DE FINANZAS|LORA750809AB1||MX|1\n"


def test_edit_resets_cursors_and_rescreens(app):
    with TestClient(app()) as c:
        login(c, *ADMIN)
        assert c.post("/api/watchlists/custom", json={"name": "PEP", "category": "pep", "csv": PEP}).status_code == 201
        t = c.post("/api/targets", json={"name": "Ana López Ruiz", "kind": "Person"}).json()
        tid = uuid.UUID(t["id"])
        c.portal.call(c.app.state.runtime.screener.cycle)
        assert len(c.get(f"/api/targets/{t['id']}/screening").json()["matches"]) == 1

        async def set_cursor():
            async with c.app.state.db.session() as s:
                s.add(db.ConnectorState(target_id=tid, source="rss", value="2026-10-27T00:00:00Z"))
                await s.commit()
        c.portal.call(set_cursor)

        # Otro objetivo con el mismo nombre y tipo no se permite.
        dup = c.post("/api/targets", json={"name": "ana lópez ruiz", "kind": "Person"})
        assert dup.status_code == 409 and "Ya existe" in dup.json()["detail"]
        other = c.post("/api/targets", json={"name": "Beatriz Soto", "kind": "Person"}).json()
        assert c.put(f"/api/targets/{other['id']}", json={"name": "Ana López Ruiz"}).status_code == 409

        # Cambiar el nombre vuelve a empezar la búsqueda y la revisión en listas.
        r = c.put(f"/api/targets/{t['id']}", json={"name": "Ana María López", "kind": "Person", "aliases": ["AML"]})
        assert r.status_code == 200 and r.json()["updatedAt"]

        async def cursor():
            async with c.app.state.db.session() as s:
                return (await s.get(db.ConnectorState, (tid, "rss"))).value
        assert c.portal.call(cursor) is None
        c.portal.call(c.app.state.runtime.screener.cycle)
        assert c.get(f"/api/targets/{t['id']}/screening").json()["matches"] == []

        # Agregar el RFC lo vuelve a encontrar aunque el nombre ya no coincida igual.
        body = {"name": "Ana María López", "kind": "Person", "aliases": ["AML", "Ana López Ruiz"],
                "identifiers": {"rfc": "lora750809ab1"}}
        assert c.put(f"/api/targets/{t['id']}", json=body).json()["identifiers"] == {"rfc": "LORA750809AB1"}
        c.portal.call(c.app.state.runtime.screener.cycle)
        assert len(c.get(f"/api/targets/{t['id']}/screening").json()["matches"]) == 1

        [event] = c.get("/api/audit", params={"action": "target.updated", "entityId": t["id"]}).json()["events"][-1:]
        assert event["changes"]["name"] == ["Ana López Ruiz", "Ana María López"]


def test_deactivate_keeps_history_and_reactivates(app):
    with TestClient(app()) as c:
        login(c, *ADMIN)
        c.post("/api/watchlists/custom", json={"name": "PEP", "category": "pep", "csv": PEP})
        t = c.post("/api/targets", json={"name": "Ana López Ruiz", "kind": "Person"}).json()
        c.portal.call(c.app.state.runtime.screener.cycle)
        assert len(c.get("/api/screening/matches").json()) == 1

        assert c.post(f"/api/targets/{t['id']}/deactivate", json={"reason": " "}).status_code == 422
        r = c.post(f"/api/targets/{t['id']}/deactivate", json={"reason": "Terminó el contrato"})
        off = r.json()
        assert r.status_code == 200 and off["enabled"] is False
        assert off["deactivatedByEmail"] == ADMIN[0] and off["deactivationReason"] == "Terminó el contrato"
        assert c.post(f"/api/targets/{t['id']}/deactivate", json={"reason": "otra vez"}).status_code == 409

        # Sigue consultable, pero fuera de la lista de activos y de las pendientes de revisar.
        assert c.get(f"/api/targets/{t['id']}").status_code == 200
        assert c.get("/api/targets", params={"status": "active"}).json() == []
        assert [x["id"] for x in c.get("/api/targets", params={"status": "inactive"}).json()] == [t["id"]]
        assert c.get("/api/screening/matches").json() == []

        async def enabled_ids():
            async with c.app.state.db.session() as s:
                return (await s.scalars(select(db.Target.id).where(db.Target.enabled.is_(True)))).all()
        assert c.portal.call(enabled_ids) == []

        # Se puede corregir estando de baja.
        assert c.put(f"/api/targets/{t['id']}", json={"name": "Ana López Ruiz", "kind": "Person",
                                                    "nationality": "México", "enabled": True}).json()["enabled"] is False

        on = c.post(f"/api/targets/{t['id']}/reactivate").json()
        assert on["enabled"] is True and on["deactivatedAt"] is None and on["deactivationReason"] is None
        assert c.post(f"/api/targets/{t['id']}/reactivate").status_code == 409
        assert len(c.get("/api/screening/matches").json()) == 1

        actions = [e["action"] for e in c.get("/api/audit", params={"entityId": t["id"]}).json()["events"]]
        assert actions[:3] == ["target.reactivated", "target.updated", "target.deactivated"]


def test_only_admins_delete_and_only_after_deactivation(app):
    with TestClient(app()) as admin, TestClient(app()) as analyst:
        login(admin, *ADMIN)
        admin.post("/api/users", json={"email": "analista@minos.mx", "role": "analyst", "password": PASSWORD})
        login(analyst, "analista@minos.mx", PASSWORD)
        t = analyst.post("/api/targets", json={"name": "Acme", "kind": "Company"}).json()
        assert admin.delete(f"/api/targets/{t['id']}").status_code == 409
        analyst.post(f"/api/targets/{t['id']}/deactivate", json={"reason": "Prueba"})
        assert analyst.delete(f"/api/targets/{t['id']}").status_code == 403
        assert admin.delete(f"/api/targets/{t['id']}").status_code == 204
        assert admin.get(f"/api/targets/{t['id']}").status_code == 404
