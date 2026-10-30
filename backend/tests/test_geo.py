"""Ubicación de menciones para el mapa: nomenclátor, pistas de cada fuente, API y ubicación de menciones viejas."""
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from conftest import POSTGRES_URL, migrate, needs_postgres, reset_postgres
from fastapi.testclient import TestClient

from minos import db
from minos.config import GeoSettings, Settings, XSettings, YouTubeSettings
from minos.connectors import ConnectorCursor, XConnector, YouTubeConnector
from minos.domain.mentions import AuthorInfo, GeoHint, MentionAnalysis, MentionDraft, Sentiment
from minos.domain.targets import MonitoredTarget
from minos.geo.locate import locate
from minos.geo.outlets import locate_outlet
from minos.geo.resolver import resolve_location, resolve_text
from minos.main import create_app


@pytest.mark.parametrize("value, expected", [
    ("Monterrey, N.L.", ("MX-NLE", "Monterrey")),
    ("CDMX", ("MX-CMX", None)),
    ("León, Gto.", ("MX-GUA", "León")),
    ("Tlalpan, CDMX", ("MX-CMX", "Tlalpan")),
    ("Col. Roma, CDMX", ("MX-CMX", None)),  # "Roma" no se va a Italia
    ("Mty, NL", ("MX-NLE", "Monterrey")),
])
def test_profile_locations_in_mexico(value, expected):
    entry = resolve_location(value)
    assert (entry.region, entry.city) == expected


def test_homonyms_follow_the_country_named_or_default_to_mexico():
    assert resolve_location("León, España").country == "ES"
    assert resolve_location("Mérida").region == "MX-YUC"
    assert resolve_location("Mérida, Venezuela").country == "VE"
    assert resolve_location("Houston, TX").city == "Houston"


def test_abbreviations_and_junk_do_not_count_as_places():
    assert resolve_location("Son de aquí") is None  # "Son." es Sonora solo tras otro lugar
    assert resolve_location("En todas partes 🌎") is None
    assert resolve_location("") is None


def test_text_needs_context_for_names_that_are_also_people_or_words():
    assert resolve_text("Miguel Hidalgo y José María Morelos") is None
    assert resolve_text("Benito Juárez inauguró la obra") is None
    assert resolve_text("Salsa de chile y tacos") is None
    assert resolve_text("Son las 5, ver más en el enlace") is None
    assert resolve_text("Lluvias en Guerrero dejan daños").region == "MX-GRO"
    assert resolve_text("Protestas en Chile").country == "CL"


def test_text_prefers_the_most_named_specific_place_and_skips_the_target_name():
    text = "El gobernador de Nuevo León visitó Guadalajara; en Monterrey hubo protesta y en Monterrey bloqueos"
    assert resolve_text(text).city == "Monterrey"
    # Si el objetivo es "Nuevo León", nombrarlo no dice dónde se habla.
    assert resolve_text("El gobierno de Nuevo León informó", ["Nuevo León"]) is None
    assert resolve_text("Ana López habló de México y de Monterrey").city == "Monterrey"


def test_outlets_by_known_domain_name_or_country_domain():
    assert locate_outlet("https://www.eluniversal.com.mx", "El Universal").region == "MX-CMX"
    assert locate_outlet("https://www.elsoldetampico.com.mx", None).city == "Tampico"
    assert locate_outlet(None, "El Siglo de Torreón").city == "Torreón"
    assert locate_outlet("https://www.clarin.com.ar", "Clarín").country == "AR"
    # Infobae tiene ediciones de varios países en el mismo dominio: no se adivina.
    assert locate_outlet("https://www.infobae.com", "Infobae") is None


def test_locate_uses_the_most_reliable_hint_first():
    s = GeoSettings()
    geotag = GeoHint(lat=25.67, lon=-100.31, place="Monterrey, Nuevo León", country_code="MX", author_location="Madrid")
    found = locate(geotag, "", [], s)
    assert (found.method, found.precision, found.city, found.lat) == ("geotag", "point", "Monterrey", 25.67)
    assert locate(GeoHint(author_location="Tijuana, BC"), "en Mérida", [], s).city == "Tijuana"
    assert locate(GeoHint(country_code="co"), "", [], s).country == "CO"
    # Sin pistas de la fuente, el texto; y se puede apagar.
    assert locate(GeoHint(author_location="mi casa"), "Marcha en Puebla", [], s).method == "text"
    assert locate(None, "Marcha en Puebla", [], GeoSettings(from_text=False)) is None
    assert locate(GeoHint(author_location="CDMX"), "", [], GeoSettings(enabled=False)) is None


def stub(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_x_sends_profile_location_and_geotag():
    payload = {
        "data": [
            {"id": "1", "text": "Ana López", "author_id": "u1", "created_at": "2026-10-25T18:00:00Z", "geo": {"place_id": "p1"}},
            {"id": "2", "text": "Ana López", "author_id": "u2", "created_at": "2026-10-25T18:01:00Z"},
        ],
        "includes": {
            "users": [{"id": "u1", "username": "a", "name": "A", "location": "Madrid"},
                      {"id": "u2", "username": "b", "name": "B", "location": "Monterrey, N.L."}],
            "places": [{"id": "p1", "full_name": "Guadalajara, Jalisco", "country_code": "MX",
                        "geo": {"bbox": [-103.4, 20.6, -103.3, 20.7]}}],
        },
        "meta": {},
    }
    requests = []

    def handler(r):
        requests.append(r)
        return httpx.Response(200, json=payload)

    first, second = [d async for d in XConnector(stub(handler), XSettings(bearer_token="t")).fetch(
        MonitoredTarget(name="Ana López"), ConnectorCursor())]
    assert first.geo.place == "Guadalajara, Jalisco"
    assert first.geo.lat == pytest.approx(20.65)
    assert second.geo == GeoHint(author_location="Monterrey, N.L.")
    assert "location" in requests[0].url.params["user.fields"]
    assert "geo.place_id" in requests[0].url.params["expansions"]


async def test_youtube_asks_channel_country_and_survives_its_failure():
    search = {"items": [{"id": {"videoId": "v1"}, "snippet": {
        "publishedAt": "2026-10-25T12:00:00Z", "channelId": "c1", "channelTitle": "Canal", "title": "Ana López"}}]}

    def ok(r):
        if r.url.path.endswith("/channels"):
            assert r.url.params["id"] == "c1"
            return httpx.Response(200, json={"items": [{"id": "c1", "snippet": {"country": "AR"}}]})
        return httpx.Response(200, json=search)

    def channels_fail(r):
        return httpx.Response(403) if r.url.path.endswith("/channels") else httpx.Response(200, json=search)

    target, settings = MonitoredTarget(name="Ana López"), YouTubeSettings(api_key="k")
    [m] = [d async for d in YouTubeConnector(stub(ok), settings).fetch(target, ConnectorCursor())]
    assert m.geo.country_code == "AR"
    [m] = [d async for d in YouTubeConnector(stub(channels_fail), settings).fetch(target, ConnectorCursor())]
    assert m.geo is None


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


def add_mentions(client, target_id: str, rows: list[tuple[str, str, GeoHint | None, Sentiment, int]]) -> None:
    """rows: (fuente, texto, pista, sentimiento, días atrás)."""
    async def run():
        async with client.app.state.db.session() as session:
            for i, (source, text, hint, sentiment, days) in enumerate(rows):
                draft = MentionDraft(source, f"{source}-{i}", "https://example.org", AuthorInfo("@a"),
                                     datetime.now(UTC) - timedelta(days=days, minutes=1), text, geo=hint)
                place = locate(hint, text, ["Ana López"], GeoSettings())
                session.add(db.Mention.create(uuid.UUID(target_id), draft, MentionAnalysis(sentiment, 0), place))
            await session.commit()
    client.portal.call(run)


def test_geo_overview_counts_by_country_state_and_place(client):
    t = client.post("/api/targets", json={"name": "Ana López", "kind": "Person"}).json()
    add_mentions(client, t["id"], [
        ("x", "Ana López", GeoHint(author_location="Monterrey, N.L."), Sentiment.NEGATIVE, 0),
        ("x", "Ana López", GeoHint(author_location="San Pedro Garza García"), Sentiment.POSITIVE, 1),
        ("rss", "Ana López en Guadalajara", GeoHint(outlet_url="https://www.eluniversal.com.mx"), Sentiment.NEUTRAL, 2),
        ("bluesky", "Ana López visitó Guadalajara", None, Sentiment.NEGATIVE, 3),
        ("bluesky", "Ana López", None, Sentiment.NEUTRAL, 3),
        ("x", "Ana López", GeoHint(author_location="Madrid"), Sentiment.NEUTRAL, 4),
        ("x", "Ana López en Monterrey", None, Sentiment.NEUTRAL, 60),  # fuera del periodo
    ])

    body = client.get(f"/api/targets/{t['id']}/geo", params={"days": 30}).json()
    assert (body["total"], body["located"], body["pending"]) == (6, 5, 0)
    assert {c["code"]: c["count"] for c in body["countries"]} == {"MX": 4, "ES": 1}
    nle = next(r for r in body["regions"] if r["code"] == "MX-NLE")
    assert (nle["name"], nle["count"], nle["negative"]) == ("Nuevo León", 2, 1)
    assert {p["name"] for p in body["places"]} >= {"Monterrey, Nuevo León", "Ciudad de México", "Guadalajara, Jalisco"}
    assert {m["method"]: m["count"] for m in body["byMethod"]} == {"profile": 3, "outlet": 1, "text": 1}
    bluesky = next(s for s in body["bySource"] if s["source"] == "bluesky")
    assert (bluesky["total"], bluesky["located"]) == (2, 1)

    origin = client.get(f"/api/targets/{t['id']}/geo", params={"basis": "origin"}).json()
    assert origin["located"] == 4
    text = client.get(f"/api/targets/{t['id']}/geo", params={"basis": "text", "source": "bluesky"}).json()
    assert (text["total"], text["located"], text["places"][0]["name"]) == (2, 1, "Guadalajara, Jalisco")

    [mention] = [m for m in client.get(f"/api/targets/{t['id']}/mentions").json() if m["placeMethod"] == "outlet"]
    assert mention["place"] == "Ciudad de México"
    assert client.get(f"/api/targets/{uuid.uuid4()}/geo").status_code == 404


def test_old_mentions_are_located_on_demand(client):
    t = client.post("/api/targets", json={"name": "Ana López", "kind": "Person"}).json()
    add_mentions(client, t["id"], [
        ("rss", "Ana López anuncia", None, Sentiment.NEUTRAL, 1),
        ("x", "Ana López en Cancún", None, Sentiment.NEUTRAL, 1),
        ("x", "Ana López", None, Sentiment.NEUTRAL, 1),
    ])

    async def forget():
        # Como si se hubieran guardado antes del mapa: sin intento de ubicación.
        async with client.app.state.db.session() as session:
            for m in (await session.scalars(db.select(db.Mention))).all():
                m.geo_method = m.geo_country = m.geo_region = m.geo_city = None
                if m.source == "rss":
                    m.author_handle = "El Siglo de Torreón"
            await session.commit()
    client.portal.call(forget)
    assert client.get(f"/api/targets/{t['id']}/geo").json()["pending"] == 3

    assert client.post(f"/api/targets/{t['id']}/geo/locate").json() == {"reviewed": 3}
    body = client.get(f"/api/targets/{t['id']}/geo").json()
    assert (body["pending"], body["located"]) == (0, 2)
    assert {p["name"] for p in body["places"]} == {"Torreón, Coahuila", "Cancún, Quintana Roo"}
    events = client.get("/api/audit", params={"action": "mentions.geolocated"}).json()["events"]
    assert events[0]["detail"] == {"reviewed": 3}
