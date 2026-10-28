"""Análisis general: ranking de sujetos por menciones, totales por tipo e históricos por mes y año."""
import uuid
from datetime import UTC, datetime

from test_api import client, create_target  # noqa: F401  (client es fixture)

from minos import db

URL = "/api/analytics/mentions"


def add_mentions(client, target_id, *rows):
    """rows: (fecha, sentimiento, fuente)."""
    async def run():
        async with client.app.state.db.session() as s:
            for at, sentiment, source in rows:
                s.add(db.Mention(
                    id=uuid.uuid4(), target_id=uuid.UUID(target_id), source=source, external_id=str(uuid.uuid4()),
                    url="https://example.com", author_handle="a", published_at=at, text="x", fingerprint=uuid.uuid4().hex,
                    sentiment=sentiment, is_severe_accusation=sentiment == "Negative" and source == "rss",
                ))
            await s.commit()
    client.portal.call(run)


def add_risk(client, target_id, *rows):
    async def run():
        async with client.app.state.db.session() as s:
            for at, index in rows:
                s.add(db.RiskSnapshot(
                    target_id=uuid.UUID(target_id), at=at, index=index, level="Low", media_score=index, survey_score=None,
                    negativity=0, severity=0, volume_anomaly=0,
                ))
            await s.commit()
    client.portal.call(run)


def d(y, m, day=15):
    return datetime(y, m, day, 12, tzinfo=UTC)


def seed(client):
    ana = create_target(client, name="Ana López", kind="Person")
    acme = create_target(client, name="Acme", kind="Company")
    pais = create_target(client, name="Narnia", kind="Country")
    add_mentions(client, ana["id"], (d(2026, 1), "Negative", "rss"), (d(2026, 1), "Positive", "x"),
                 (d(2026, 3), "Neutral", "rss"), (d(2025, 6), "Negative", "x"))
    add_mentions(client, acme["id"], (d(2026, 2), "Negative", "x"), (d(2026, 3), "Negative", "x"))
    add_mentions(client, pais["id"], (d(2026, 3), "Positive", "rss"))
    add_risk(client, ana["id"], (d(2026, 1, 1), 20), (d(2026, 1, 20), 40), (d(2026, 3), 60))
    add_risk(client, acme["id"], (d(2026, 3), 30))
    return ana, acme, pais


def test_ranking_and_monthly_history(client):
    ana, acme, pais = seed(client)

    r = client.get(URL, params={"since": "2026-01", "until": "2026-04"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["periods"] == ["2026-01", "2026-02", "2026-03", "2026-04"]
    assert [(s["name"], s["mentions"]) for s in body["ranking"]] == [("Ana López", 3), ("Acme", 2), ("Narnia", 1)]
    first = body["ranking"][0]
    assert (first["positive"], first["neutral"], first["negative"], first["severe"]) == (1, 1, 1, 1)
    assert first["lastIndex"] == 60
    kinds = {k["kind"]: k for k in body["byKind"]}
    assert kinds["Person"]["mentions"] == 3 and kinds["Company"]["negative"] == 2 and kinds["Institution"]["targets"] == 0
    assert {(x["period"], x["kind"], x["count"]) for x in body["mentionsByKind"]} == {
        ("2026-01", "Person", 2), ("2026-02", "Company", 1), ("2026-03", "Company", 1),
        ("2026-03", "Person", 1), ("2026-03", "Country", 1),
    }
    ana_series = {x["period"]: x["count"] for x in body["mentionsByTarget"] if x["targetId"] == ana["id"]}
    assert ana_series == {"2026-01": 2, "2026-03": 1}
    risk = {(x["period"], x["targetId"]): (x["avg"], x["max"]) for x in body["riskByTarget"]}
    assert risk[("2026-01", ana["id"])] == (30, 40)
    # Promedio por tipo: Ana 60 (persona) y Acme 30 (empresa) en marzo.
    assert {(x["period"], x["kind"]): x["avg"] for x in body["riskByKind"]}[("2026-03", "Company")] == 30


def test_yearly_filters_by_kind_and_source_and_skips_inactive(client):
    ana, acme, pais = seed(client)

    yearly = client.get(URL, params={"granularity": "year", "until": "2026"}).json()
    assert yearly["periods"] == ["2025", "2026"]
    assert {(x["period"], x["count"]) for x in yearly["mentionsByTarget"] if x["targetId"] == ana["id"]} == {
        ("2025", 1), ("2026", 3),
    }

    companies = client.get(URL, params={"since": "2026-01", "until": "2026-03", "kind": "Company"}).json()
    assert [s["name"] for s in companies["ranking"]] == ["Acme"]
    assert [k["kind"] for k in companies["byKind"]] == ["Company"]

    news = client.get(URL, params={"since": "2026-01", "until": "2026-03", "source": "rss"}).json()
    assert [(s["name"], s["mentions"]) for s in news["ranking"]] == [("Ana López", 2), ("Narnia", 1), ("Acme", 0)]

    client.put(f"/api/targets/{acme['id']}", json={"name": "Acme", "kind": "Company", "enabled": False})
    active = client.get(URL, params={"since": "2026-01", "until": "2026-03"}).json()
    assert "Acme" not in [s["name"] for s in active["ranking"]]
    assert all(x["kind"] != "Company" for x in active["mentionsByKind"])
    every = client.get(URL, params={"since": "2026-01", "until": "2026-03", "includeInactive": "true"}).json()
    assert "Acme" in [s["name"] for s in every["ranking"]]


def test_default_range_is_last_twelve_months_and_bad_ranges_fail(client):
    body = client.get(URL).json()
    assert len(body["periods"]) == 12 and body["ranking"] == []
    assert client.get(URL, params={"since": "2026-05", "until": "2026-01"}).status_code == 400
    assert client.get(URL, params={"since": "2026-13"}).status_code == 422
