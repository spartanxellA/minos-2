"""Temas más mencionados de un objetivo (nube de palabras): extracción y API."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from conftest import POSTGRES_URL, migrate, needs_postgres, reset_postgres
from fastapi.testclient import TestClient

from minos import db
from minos.config import Settings
from minos.domain.mentions import AuthorInfo, MentionAnalysis, MentionDraft, Sentiment
from minos.main import create_app
from minos.topics import extract_topics, name_words


def terms(mentions, exclude=frozenset(), limit=80):
    return {t.term: t for t in extract_topics(mentions, exclude, limit)[1]}


def test_stopwords_in_spanish_english_and_french_are_skipped():
    found = terms([
        ("El gobierno y la reforma que se aprobó", "Neutral"),
        ("The government and the reform that was approved", "Neutral"),
        ("Le gouvernement et la réforme qui a été approuvée", "Neutral"),
    ])
    assert {"gobierno", "reforma", "government", "reform", "gouvernement", "réforme"} <= set(found)
    assert not {"que", "the", "and", "qui", "été", "El", "Le"} & set(found)


def test_target_name_links_handles_and_noise_do_not_count():
    found = terms([
        ("Ana López habla de seguridad https://t.co/abc @prensa RT jajaja", "Neutral"),
        ("ana lopez y la seguridad www.ejemplo.com", "Neutral"),
    ], name_words(["Ana López", "@analopez"]))
    assert set(found) == {"seguridad"}
    assert found["seguridad"].count == 2


def test_counts_mentions_not_repetitions_and_keeps_the_common_spelling():
    found = terms([
        ("Pemex Pemex Pemex", "Negative"),
        ("pemex otra vez", "Positive"),
        ("PEMEX y Pemex", "Neutral"),
    ])
    pemex = found["Pemex"]
    assert (pemex.count, pemex.negative, pemex.positive) == (3, 1, 1)


def test_phrases_and_hashtags_absorb_words_that_only_appear_inside_them():
    found = terms([
        ("Falla en la Línea 12 del metro #NoMásApagones", "Negative"),
        ("Otra vez la línea 12, qué desastre. #NoMasApagones", "Negative"),
        ("La Línea 12 sigue cerrada", "Neutral"),
    ])
    assert found["Línea 12"].kind == "phrase" and found["Línea 12"].count == 3
    assert "Línea" not in found and "línea" not in found
    # Con o sin acento es el mismo hashtag.
    tag = next(t for t in found.values() if t.kind == "hashtag")
    assert tag.count == 2 and tag.term.lower().startswith("#nom")
    # Las frases no cruzan de una oración a otra.
    assert "desastre NoMasApagones" not in found


def test_phrases_can_skip_a_linking_word_and_keep_place_names():
    found = terms([
        ("La crisis del agua en Nuevo León", "Negative"),
        ("Sigue la crisis del agua", "Negative"),
        ("Inversión extranjera en Nuevo León", "Positive"),
        ("Llega inversión extranjera", "Positive"),
        ("Más inversión extranjera", "Positive"),
    ])
    assert found["crisis del agua"].count == 2 and "crisis" not in found and "agua" not in found
    assert found["Nuevo León"].count == 2
    # Gana la minúscula cuando la mayúscula solo viene de iniciar la oración.
    assert "inversión extranjera" in found


def test_single_mentions_are_dropped_once_there_is_enough_volume():
    mentions = [("inflación y empleo", "Neutral")] * 25 + [("palabrarara", "Neutral")]
    found = terms(mentions)
    assert "palabrarara" not in found and found["inflación"].count == 25
    assert len(terms(mentions, limit=1)) == 1


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=needs_postgres)])
def client(request, tmp_path):
    if request.param == "postgres":
        reset_postgres(POSTGRES_URL)
        migrate(POSTGRES_URL)
        settings = Settings(env="development", database_url=POSTGRES_URL, role="api", auth={"mode": "off"})
    else:
        url = f"sqlite+aiosqlite:///{tmp_path / 'minos.db'}"
        settings = Settings(env="development", database_url=url, role="api", create_schema=True, auth={"mode": "off"})
    with TestClient(create_app(settings)) as c:
        yield c


def add_mentions(client, target_id: str, rows: list[tuple[str, str, Sentiment, int]]) -> None:
    """rows: (fuente, texto, sentimiento, días atrás)."""
    async def run():
        async with client.app.state.db.session() as session:
            for i, (source, text, sentiment, days) in enumerate(rows):
                draft = MentionDraft(source, f"{source}-{i}", "https://example.org", AuthorInfo("@a"),
                                     datetime.now(UTC) - timedelta(days=days, minutes=1), text)
                session.add(db.Mention.create(uuid.UUID(target_id), draft, MentionAnalysis(sentiment, 0), None))
            await session.commit()
    client.portal.call(run)


def test_topics_api_filters_by_period_source_and_sentiment(client):
    t = client.post("/api/targets", json={"name": "Ana López", "kind": "Person", "aliases": ["La Gobernadora"]}).json()
    add_mentions(client, t["id"], [
        ("x", "Ana López y el fraude electoral", Sentiment.NEGATIVE, 0),
        ("x", "La gobernadora niega el fraude electoral", Sentiment.NEGATIVE, 1),
        ("rss", "Ana López inaugura hospital #Salud", Sentiment.POSITIVE, 2),
        ("rss", "Nuevo hospital en Monterrey #Salud", Sentiment.POSITIVE, 3),
        ("x", "Ana López y el puente viejo", Sentiment.NEUTRAL, 60),  # fuera del periodo
    ])
    url = f"/api/targets/{t['id']}/topics"

    body = client.get(url, params={"days": 30}).json()
    assert (body["days"], body["total"], body["analyzed"]) == (30, 4, 4)
    found = {x["term"]: x for x in body["terms"]}
    assert found["fraude electoral"] == {"term": "fraude electoral", "kind": "phrase", "count": 2, "positive": 0, "negative": 2}
    assert found["#Salud"]["kind"] == "hashtag" and found["hospital"]["count"] == 2
    assert not {"Ana", "López", "gobernadora", "puente"} & set(found)

    assert "puente" in {x["term"] for x in client.get(url, params={"days": 90}).json()["terms"]}
    rss = client.get(url, params={"source": "rss"}).json()
    assert rss["total"] == 2 and "fraude electoral" not in {x["term"] for x in rss["terms"]}
    negative = client.get(url, params={"sentiment": "negative"}).json()
    assert {x["term"] for x in negative["terms"]} >= {"fraude electoral"} and "hospital" not in {x["term"] for x in negative["terms"]}

    assert client.get(url, params={"days": 0}).status_code == 422
    assert client.get(f"/api/targets/{uuid.uuid4()}/topics").status_code == 404
