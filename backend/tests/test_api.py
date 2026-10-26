"""API, pipeline y WebSocket de punta a punta sobre SQLite en memoria, con el conector de demostración."""
import pytest
from conftest import POSTGRES_URL, migrate, needs_postgres, reset_postgres
from fastapi.testclient import TestClient

from minos.analysis import LexiconAnalyzer
from minos.config import DemoSettings, IngestionSettings, Settings
from minos.connectors import DemoConnector
from minos.main import create_app
from minos.pipeline import IngestionWorker


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=needs_postgres)])
def client(request, tmp_path):
    if request.param == "postgres":
        # PostgreSQL migrado con Alembic, como en producción (con TimescaleDB si está disponible).
        reset_postgres(POSTGRES_URL)
        migrate(POSTGRES_URL)
        settings = Settings(env="development", database_url=POSTGRES_URL, role="api")
    else:
        url = f"sqlite+aiosqlite:///{tmp_path / 'minos.db'}"
        settings = Settings(env="development", database_url=url, role="api", create_schema=True)
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


def test_survey_history_returns_latest_answers_first(client):
    t = create_target(client)
    survey = client.get("/api/surveys/RASurvey").json()
    questions = [q for s in survey["sections"] for q in s["questions"]]
    best = {q["id"]: min(q["options"], key=lambda o: o["weight"])["value"] for q in questions}
    worst = {q["id"]: max(q["options"], key=lambda o: o["weight"])["value"] for q in questions}
    url = f"/api/targets/{t['id']}/survey-responses"

    assert client.get(url).json() == []
    client.post(url, json={"surveyId": "RASurvey", "answers": best})
    client.post(url, json={"surveyId": "RASurvey", "answers": worst})

    history = client.get(url, params={"surveyId": "RASurvey"}).json()
    assert [h["score"] for h in history] == [100, 0]
    assert history[0]["answers"] == worst
    assert history[0]["sectionValues"] == {s["id"]: 100 for s in survey["sections"]}
    assert client.get(url, params={"surveyId": "PDSurvey"}).json() == []


def test_survey_rejects_incomplete_or_invalid_answers(client):
    t = create_target(client)
    survey = client.get("/api/surveys/RASurvey").json()
    first, second = survey["sections"][0]["questions"][:2]
    url = f"/api/targets/{t['id']}/survey-responses"

    r = client.post(url, json={"surveyId": "RASurvey", "answers": {first["id"]: "A", second["id"]: "Z", "NOPE": "A"}})

    assert r.status_code == 422
    problems = r.json()["detail"]["problems"]
    assert f"{second['id']}: opción inválida 'Z'" in problems
    assert "NOPE: pregunta desconocida" in problems
    assert sum("falta la respuesta" in p for p in problems) == 44  # 46 preguntas, 2 con respuesta
    assert client.get(url).json() == []
    # El de perfil no puntúa: se guarda aunque esté a medias.
    assert client.post(url, json={"surveyId": "PDSurvey", "answers": {}}).status_code == 200


def test_pipeline_ingests_analyzes_scores_and_pushes_live(client):
    t = create_target(client)
    app = client.app
    worker = IngestionWorker(
        app.state.db, [DemoConnector(DemoSettings(enabled=True))], LexiconAnalyzer(), app.state.bus, IngestionSettings(),
    )

    with client.websocket_connect(f"/ws/targets/{t['id']}") as ws:
        client.portal.call(worker.run_once)
        added = ws.receive_json()
        assert added["event"] == "mentionsAdded"
        assert added["data"][0]["sentiment"] in {"positive", "negative", "neutral"}

        [queued] = client.portal.call(app.state.bus.next_recompute, 1)
        assert str(queued) == t["id"]
        client.portal.call(app.state.risk_engine.recompute, queued)
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
