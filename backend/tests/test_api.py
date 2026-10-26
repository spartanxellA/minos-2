"""API, pipeline y WebSocket de punta a punta sobre SQLite en memoria, con el conector de demostración."""
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import delete
from conftest import POSTGRES_URL, migrate, needs_postgres, reset_postgres
from fastapi.testclient import TestClient

from minos.analysis import LexiconAnalyzer
from minos import db
from minos.config import DemoSettings, IngestionSettings, JetstreamSettings, NotificationSettings, RiskEngineSettings, Settings
from minos.connectors import DemoConnector
from minos.domain.mentions import AuthorInfo, MentionDraft
from minos.domain.targets import MonitoredTarget
from minos.main import create_app
from minos.notifications import Notifier
from minos.pipeline import IngestionWorker, RiskEngine
from minos.pipeline.stream import JetstreamIngestion


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=needs_postgres)])
def client(request, tmp_path):
    if request.param == "postgres":
        # PostgreSQL migrado con Alembic, como en producción (con TimescaleDB si está disponible).
        reset_postgres(POSTGRES_URL)
        migrate(POSTGRES_URL)
        settings = Settings(env="development", database_url=POSTGRES_URL, role="api", auth={"mode": "off"})
    else:
        url = f"sqlite+aiosqlite:///{tmp_path / 'minos.db'}"
        settings = Settings(env="development", database_url=url, role="api", create_schema=True, auth={"mode": "off"})
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


class OwnPageConnector:
    """Comentarios en la página propia: hablan del objetivo aunque no lo nombren."""

    source = "facebook"
    is_configured = True
    poll_interval = timedelta(0)

    async def fetch(self, target, cursor):
        now = datetime.now(UTC)
        yield MentionDraft("facebook", "c1", "https://facebook.com/1", AuthorInfo("Laura"), now, "Qué vergüenza de servicio", own_channel=True)
        yield MentionDraft("facebook", "c2", "https://facebook.com/2", AuthorInfo("Pedro"), now, "   ", own_channel=True)
        yield MentionDraft("facebook", "p3", "https://facebook.com/3", AuthorInfo("Otro"), now, "Nada que ver con nadie")


def test_own_channel_comments_skip_the_name_filter(client):
    t = create_target(client)
    app = client.app
    worker = IngestionWorker(app.state.db, [OwnPageConnector()], LexiconAnalyzer(), app.state.bus, IngestionSettings())

    client.portal.call(worker.run_once)

    mentions = client.get(f"/api/targets/{t['id']}/mentions").json()
    assert [m["text"] for m in mentions] == ["Qué vergüenza de servicio"]


class LongIdConnector:
    """Como Google Noticias: el id de la nota es un enlace de más de 512 caracteres."""

    source = "rss"
    is_configured = True
    poll_interval = timedelta(0)
    calls = 0

    async def fetch(self, target, cursor):
        self.calls += 1  # el texto cambia en cada ronda: solo el id evita que se repita
        link = "https://news.google.com/rss/articles/" + "x" * 900
        yield MentionDraft("rss", link, link, AuthorInfo("D" * 300, "D" * 300), datetime.now(UTC),
                           f"Ana López presenta su informe, ronda {self.calls}")


def test_long_external_ids_and_authors_fit_and_still_dedupe(client):
    t = create_target(client)
    app = client.app
    worker = IngestionWorker(app.state.db, [LongIdConnector()], LexiconAnalyzer(), app.state.bus, IngestionSettings())

    client.portal.call(worker.run_once)
    client.portal.call(worker.run_once)

    [m] = client.get(f"/api/targets/{t['id']}/mentions").json()
    assert m["url"].endswith("x" * 900)
    assert len(m["author"]) <= 201
    [state] = client.get(f"/api/targets/{t['id']}/connectors").json()
    assert state["lastError"] is None


def test_jetstream_stores_matching_posts_and_pushes_them_live(client):
    t = create_target(client)
    app = client.app
    worker = IngestionWorker(app.state.db, [], LexiconAnalyzer(), app.state.bus, IngestionSettings())
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"profiles": [
        {"did": "did:plc:a", "handle": "diario.bsky.social", "followersCount": 200000},
    ]})))
    stream = JetstreamIngestion(app.state.db, worker, app.state.bus, http, JetstreamSettings())
    stream.set_targets([MonitoredTarget(name="Ana López", id=uuid.UUID(t["id"]), excluded_terms=["López Obrador"])])

    def event(text, rkey):
        return {"did": "did:plc:a", "time_us": 1, "kind": "commit", "commit": {
            "operation": "create", "collection": "app.bsky.feed.post", "rkey": rkey,
            "record": {"text": text, "createdAt": datetime.now(UTC).isoformat()}}}

    with client.websocket_connect(f"/ws/targets/{t['id']}") as ws:
        stream.handle(event("Denuncian fraude de Ana López", "1"))
        stream.handle(event("Ana López, otra vez", "1"))  # mismo post repetido: se descarta
        stream.handle(event("Habló López Obrador", "2"))
        stream.handle(event("Algo sin relación", "3"))
        client.portal.call(stream.flush)
        added = ws.receive_json()

    assert added["event"] == "mentionsAdded"
    [m] = added["data"]
    assert m["author"] == "@diario.bsky.social"
    assert m["followers"] == 200000
    assert m["url"] == "https://bsky.app/profile/diario.bsky.social/post/1"
    [queued] = client.portal.call(app.state.bus.next_recompute, 1)
    assert str(queued) == t["id"]


class Inbox:
    name = "inbox"
    is_configured = True

    def __init__(self):
        self.got = []

    async def send(self, notice):
        self.got.append(notice)


def test_lasting_alerts_are_recorded_and_notified_once_per_cooldown(client):
    t = create_target(client)
    target_id = uuid.UUID(t["id"])
    app = client.app
    inbox = Inbox()
    notifier = Notifier([inbox], NotificationSettings(dashboard_url="https://minos.example"))
    engine = RiskEngine(app.state.db, app.state.bus, RiskEngineSettings(), notifier)

    async def yesterday_at_zero():
        async with app.state.db.session() as session:
            session.add(db.RiskSnapshot(
                target_id=target_id, at=datetime.now(UTC) - timedelta(hours=25), index=0, level="Low", media_score=0,
                survey_score=None, negativity=0, severity=0, volume_anomaly=0, mention_count=0, positive=0, negative=0,
                neutral=0, top_drivers=[],
            ))
            await session.commit()

    client.portal.call(yesterday_at_zero)
    survey = client.get("/api/surveys/RASurvey").json()
    worst = {q["id"]: max(q["options"], key=lambda o: o["weight"])["value"] for s in survey["sections"] for q in s["questions"]}
    client.post(f"/api/targets/{t['id']}/survey-responses", json={"surveyId": "RASurvey", "answers": worst})
    # La respuesta ya disparó un recálculo con el motor de la app (sin canales); se borra para empezar limpio.
    async def clear_alerts():
        async with app.state.db.session() as session:
            await session.execute(delete(db.AlertRecord))
            await session.commit()
    client.portal.call(clear_alerts)

    for _ in range(3):  # el índice sigue 40 puntos arriba en cada recálculo
        client.portal.call(engine.recompute, target_id)
    client.portal.call(notifier.drain)

    alerts = client.get(f"/api/targets/{t['id']}/alerts").json()
    assert [a["kind"] for a in alerts] == ["IndexJump"]
    [notice] = inbox.got
    assert notice.target_name == "Ana López"
    assert notice.title == "Cambio de tendencia"
    assert notice.index == 40
    assert notice.dashboard_url == f"https://minos.example/?target={t['id']}"
