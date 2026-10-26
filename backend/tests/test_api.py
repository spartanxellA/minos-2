"""API, pipeline y WebSocket de punta a punta sobre SQLite en memoria, con el conector de demostración."""
import pytest
from fastapi.testclient import TestClient

from minos.analysis import LexiconAnalyzer
from minos.config import DemoSettings, IngestionSettings, Settings
from minos.connectors import DemoConnector
from minos.main import create_app
from minos.pipeline import IngestionWorker


@pytest.fixture
def client(tmp_path):
    settings = Settings(env="development", database_url=f"sqlite+aiosqlite:///{tmp_path / 'minos.db'}", run_workers=False)
    with TestClient(create_app(settings)) as c:
        yield c


def create_target(client, **extra):
    body = {"name": "Ana López", "kind": "Person", "aliases": ["Secretaria López", " "], "excludedTerms": ["López Obrador"]}
    response = client.post("/api/targets", json=body | extra)
    assert response.status_code == 201, response.text
    return response.json()


def test_targets_crud_uses_camel_case(client):
    t = create_target(client)
    assert t["kind"] == "Person"
    assert t["aliases"] == ["Secretaria López"]
    assert t["excludedTerms"] == ["López Obrador"]

    updated = client.put(f"/api/targets/{t['id']}", json={"name": "Ana López", "kind": "GovernmentArea"}).json()
    assert updated["kind"] == "GovernmentArea"
    assert [x["id"] for x in client.get("/api/targets").json()] == [t["id"]]

    assert client.delete(f"/api/targets/{t['id']}").status_code == 204
    assert client.get(f"/api/targets/{t['id']}").status_code == 404


def test_rejects_unknown_kind(client):
    assert client.post("/api/targets", json={"name": "X", "kind": "Planet"}).status_code == 422


def test_survey_response_is_scored_and_moves_the_index(client):
    t = create_target(client)
    survey = client.get("/api/surveys/RASurvey").json()
    worst = {q["id"]: max(q["options"], key=lambda o: o["weight"])["value"]
             for s in survey["sections"] for q in s["questions"]}

    r = client.post(f"/api/targets/{t['id']}/survey-responses", json={"surveyId": "RASurvey", "answers": worst})

    assert r.status_code == 200, r.text
    assert r.json()["score"] == 100
    latest = client.get(f"/api/targets/{t['id']}/risk/latest").json()
    # Sin menciones M = 0, así que IRR = 0.6 × 0 + 0.4 × 100.
    assert latest["index"] == 40
    assert latest["surveyScore"] == 100
    assert latest["label"] == "Riesgo medio"


def test_pipeline_ingests_analyzes_scores_and_pushes_live(client):
    t = create_target(client)
    app = client.app
    queued = []
    worker = IngestionWorker(
        app.state.db, [DemoConnector(DemoSettings(enabled=True))], LexiconAnalyzer(), app.state.hub,
        IngestionSettings(), queued.append,
    )

    with client.websocket_connect(f"/ws/targets/{t['id']}") as ws:
        client.portal.call(worker.run_once)
        added = ws.receive_json()
        assert added["event"] == "mentionsAdded"
        assert added["data"][0]["sentiment"] in {"positive", "negative", "neutral"}

        client.portal.call(app.state.risk_engine.recompute, queued[0])
        risk = ws.receive_json()
        assert risk["event"] == "riskUpdated"
        assert 0 <= risk["data"]["index"] <= 100
        assert risk["data"]["mentions"] == len(added["data"])

    mentions = client.get(f"/api/targets/{t['id']}/mentions").json()
    assert len(mentions) == len(added["data"])
    breakdown = client.get(f"/api/targets/{t['id']}/breakdown").json()
    assert sum(r["count"] for r in breakdown["bySourceAndSentiment"]) == len(mentions)
    assert breakdown["influencers"]
    [state] = client.get(f"/api/targets/{t['id']}/connectors").json()
    assert state["source"] == "demo" and state["lastError"] is None

    # Segunda ronda inmediata: el intervalo del conector no ha pasado, no se vuelve a consultar.
    client.portal.call(worker.run_once)
    assert len(client.get(f"/api/targets/{t['id']}/mentions").json()) == len(mentions)
