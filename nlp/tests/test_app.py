from fastapi.testclient import TestClient

from minos_nlp import lexicon
from minos_nlp.app import app

client = TestClient(app)


def test_lexicon_detects_severe_accusation_without_accents():
    r = lexicon.analyze("Acusan a la secretaria de CORRUPCIÓN y fraude")
    assert r["sentiment"] == "negative"
    assert r["severe_accusation"] is True


def test_lexicon_positive_and_neutral():
    assert lexicon.analyze("Excelente logro del equipo")["sentiment"] == "positive"
    assert lexicon.analyze("Reunión el martes")["sentiment"] == "neutral"


def test_analyze_endpoint_returns_one_result_per_item_with_camel_case():
    body = {"target": "Ana López", "items": [{"text": "Críticas a Ana López"}, {"text": "Gran logro de Ana López"}]}
    res = client.post("/v1/analyze", json=body)
    assert res.status_code == 200
    results = res.json()["results"]
    assert [r["sentiment"] for r in results] == ["negative", "positive"]
    assert "severeAccusation" in results[0]


def test_health_reports_engines():
    assert client.get("/health").json()["sentiment"] == "lexicon"


def test_ambiguous_items_go_to_deep_analysis(monkeypatch):
    from minos_nlp import app as app_module

    seen: list[list[str]] = []

    async def fake_analyze(target, texts, examples=None):
        seen.append(texts)
        return [None] * len(texts)

    monkeypatch.setattr(app_module.deep, "analyze", fake_analyze)
    body = {"target": "Lula", "items": [{"text": "Lula viaja a China"},
                                        {"text": "Lula no es malo, solo le falta apoyo en el congreso"}]}
    assert client.post("/v1/analyze", json=body).status_code == 200
    assert seen == [["Lula no es malo, solo le falta apoyo en el congreso"]]


def test_examples_reach_deep_analysis(monkeypatch):
    from minos_nlp import app as app_module

    got: list = []

    async def fake_analyze(target, texts, examples=None):
        got.append(examples)
        return [None] * len(texts)

    monkeypatch.setattr(app_module.deep, "analyze", fake_analyze)
    body = {"target": "Alito", "items": [{"text": "Alito agrede a ciudadano"}],
            "examples": [{"text": "Alito pierde los estribos", "sentiment": "negative"}]}
    assert client.post("/v1/analyze", json=body).status_code == 200
    assert got == [[{"text": "Alito pierde los estribos", "sentiment": "negative"}]]
