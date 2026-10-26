"""Conectores de la fase 2 (Reddit, Facebook, Instagram, Bluesky en vivo) contra respuestas simuladas."""
from datetime import UTC, datetime

import httpx
import pytest
from test_connectors import stub

from minos.config import JetstreamSettings, MetaSettings, RedditSettings
from minos.connectors import ConnectorCursor, FacebookPageConnector, InstagramConnector, RedditConnector
from minos.connectors.jetstream import ProfileDirectory, parse_event, subscribe_url
from minos.connectors.meta import GraphApiError
from minos.domain.targets import MonitoredTarget

TARGET = MonitoredTarget(name="Ana López", handles={"facebook": "111", "instagram": "222"})
CURSOR = "2026-10-25T00:00:00+00:00"


async def collect(connector, cursor, target=TARGET):
    return [d async for d in connector.fetch(target, cursor)]


# --- Reddit ---------------------------------------------------------------------------------------

def reddit_post(name, created, **extra):
    return {"kind": "t3", "data": {
        "name": name, "title": "Ana López y el presupuesto", "selftext": "Detalles", "author": "vecino",
        "subreddit_name_prefixed": "r/mexico", "created_utc": created, "permalink": f"/r/mexico/comments/{name}/x/",
        "score": 42, "num_comments": 7, "num_crossposts": 1, **extra,
    }}


async def test_reddit_gets_app_token_searches_and_maps_posts():
    new = datetime(2026, 10, 25, 12, tzinfo=UTC).timestamp()
    old = datetime(2026, 10, 24, tzinfo=UTC).timestamp()

    def handler(request: httpx.Request):
        if request.url.path == "/api/v1/access_token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(200, json={"data": {"children": [reddit_post("t3_new", new), reddit_post("t3_old", old)]}})

    http, requests = stub(handler)
    connector = RedditConnector(http, RedditSettings(client_id="id", client_secret="s", user_agent="minOS/2.0 (by u/x)",
                                                     subreddits=["mexico", "cdmx"]))
    cursor = ConnectorCursor(CURSOR)

    [m] = await collect(connector, cursor)

    assert m.external_id == "t3_new"
    assert m.url == "https://www.reddit.com/r/mexico/comments/t3_new/x/"
    assert m.author.handle == "u/vecino"
    assert m.text == "Ana López y el presupuesto\n\nDetalles"
    assert (m.engagement.likes, m.engagement.replies, m.engagement.shares) == (42, 7, 1)
    assert cursor.value == datetime.fromtimestamp(new, UTC).isoformat()
    token, search = requests
    assert token.headers["authorization"].startswith("Basic ")
    assert search.url.path == "/r/mexico+cdmx/search"
    assert search.url.params["restrict_sr"] == "1"
    assert search.url.params["sort"] == "new"
    assert search.headers["authorization"] == "Bearer tok"
    assert search.headers["user-agent"] == "minOS/2.0 (by u/x)"

    await collect(connector, ConnectorCursor(CURSOR))
    assert len(requests) == 3  # el token se reutiliza mientras no venza


def test_reddit_without_credentials_is_off():
    assert not RedditConnector(httpx.AsyncClient(), RedditSettings()).is_configured


# --- Facebook -------------------------------------------------------------------------------------

FB_FEED = {"data": [
    {"id": "111_1", "message": "Aviso oficial", "created_time": "2026-10-25T10:00:00+0000", "from": {"id": "111"},
     "permalink_url": "https://facebook.com/111/posts/1",
     "comments": {"data": [
         {"id": "c1", "message": "Qué vergüenza", "created_time": "2026-10-25T11:00:00+0000",
          "from": {"id": "9", "name": "Laura"}, "like_count": 3, "comment_count": 1},
         {"id": "c2", "message": "Gracias por su comentario", "created_time": "2026-10-25T11:30:00+0000", "from": {"id": "111"}},
         {"id": "c0", "message": "Viejo", "created_time": "2026-10-24T11:00:00+0000", "from": {"id": "8"}},
     ]}},
    {"id": "111_2", "message": "Publicación de un visitante", "created_time": "2026-10-25T09:00:00+0000",
     "from": {"id": "7", "name": "Pedro"}},
]}
FB_TAGGED = {"data": [{"id": "5_1", "message": "Etiqueta a la página", "created_time": "2026-10-25T08:00:00+0000",
                       "from": {"id": "5", "name": "Diario"}, "permalink_url": "https://facebook.com/5/posts/1"}]}


async def test_facebook_reads_comments_visitor_posts_and_tags_but_not_the_page_itself():
    http, requests = stub(lambda r: httpx.Response(200, json=FB_TAGGED if r.url.path.endswith("/tagged") else FB_FEED))
    connector = FacebookPageConnector(http, MetaSettings(access_token="tok"))
    cursor = ConnectorCursor(CURSOR)

    drafts = await collect(connector, cursor)

    assert [d.external_id for d in drafts] == ["c1", "111_2", "5_1"]
    assert all(d.own_channel for d in drafts)
    assert drafts[0].author.handle == "Laura"
    assert drafts[0].url == "https://facebook.com/111/posts/1"  # el comentario sin enlace usa el de la publicación
    assert drafts[0].engagement.likes == 3
    assert cursor.value == "2026-10-25T11:00:00+00:00"
    assert [r.url.path for r in requests] == ["/v23.0/111/feed", "/v23.0/111/tagged"]
    assert requests[0].url.params["access_token"] == "tok"


async def test_meta_skips_targets_without_their_account_and_reports_graph_errors():
    http, requests = stub(lambda r: httpx.Response(400, json={"error": {"message": "Missing permission"}}))
    connector = FacebookPageConnector(http, MetaSettings(access_token="tok"))

    assert await collect(connector, ConnectorCursor(), MonitoredTarget(name="Sin página")) == []
    assert requests == []
    with pytest.raises(GraphApiError, match="Missing permission"):
        await collect(connector, ConnectorCursor())


# --- Instagram ------------------------------------------------------------------------------------

async def test_instagram_reads_comments_and_tags_but_not_its_own_replies():
    def handler(request: httpx.Request):
        path = request.url.path
        if path.endswith("/media"):
            return httpx.Response(200, json={"data": [{"id": "m1", "permalink": "https://instagram.com/p/1", "comments": {"data": [
                {"id": "ic1", "text": "Pésimo servicio", "timestamp": "2026-10-25T12:00:00+0000", "username": "cliente", "like_count": 2},
                {"id": "ic2", "text": "Lo revisamos", "timestamp": "2026-10-25T12:05:00+0000", "username": "ana.oficial"},
            ]}}]})
        if path.endswith("/tags"):
            return httpx.Response(200, json={"data": [{"id": "t1", "caption": "Con @ana.oficial", "timestamp": "2026-10-25T13:00:00+0000",
                                                       "permalink": "https://instagram.com/p/2", "username": "fan", "like_count": 9}]})
        return httpx.Response(200, json={"username": "ana.oficial", "id": "222"})

    http, requests = stub(handler)
    connector = InstagramConnector(http, MetaSettings(access_token="tok"))

    drafts = await collect(connector, ConnectorCursor(CURSOR))

    assert [(d.external_id, d.author.handle) for d in drafts] == [("ic1", "@cliente"), ("t1", "@fan")]
    assert drafts[0].url == "https://instagram.com/p/1"
    await collect(connector, ConnectorCursor(CURSOR))
    assert sum(r.url.path == "/v23.0/222" for r in requests) == 1  # el nombre de la cuenta se pide una vez


# --- Bluesky en vivo (Jetstream) ------------------------------------------------------------------

def jet_event(text, operation="create", collection="app.bsky.feed.post", did="did:plc:abc", rkey="3k1"):
    return {"did": did, "time_us": 1761400000000000, "kind": "commit", "commit": {
        "operation": operation, "collection": collection, "rkey": rkey,
        "record": {"text": text, "createdAt": "2026-10-25T18:00:00.000Z", "langs": ["es"]},
    }}


def test_jetstream_parses_only_new_posts():
    post = parse_event(jet_event("Hola Ana López"))
    assert post.uri == "at://did:plc:abc/app.bsky.feed.post/3k1"
    assert post.language == "es"
    assert parse_event(jet_event("x", operation="delete")) is None
    assert parse_event(jet_event("x", collection="app.bsky.feed.like")) is None
    assert parse_event(jet_event("   ")) is None
    assert parse_event({"kind": "identity", "did": "did:plc:abc"}) is None
    assert "cursor=123" in subscribe_url(JetstreamSettings(), 123)


async def test_jetstream_profiles_are_resolved_in_batches_and_cached():
    def handler(request: httpx.Request):
        actors = request.url.params.get_list("actors")
        return httpx.Response(200, json={"profiles": [
            {"did": d, "handle": f"{d[-3:]}.bsky.social", "displayName": "Nombre", "followersCount": 150000} for d in actors
        ]})

    http, requests = stub(handler)
    directory = ProfileDirectory(http, JetstreamSettings())
    dids = {f"did:plc:{i:03}" for i in range(30)}

    authors = await directory.resolve(dids)
    await directory.resolve({"did:plc:001"})

    assert len(requests) == 2  # 25 + 5, y la segunda vez sale de la caché
    assert authors["did:plc:001"].handle == "@001.bsky.social"
    draft = ProfileDirectory.draft(parse_event(jet_event("Ana López", did="did:plc:001")), authors["did:plc:001"])
    assert draft.url == "https://bsky.app/profile/001.bsky.social/post/3k1"
    assert draft.author.followers == 150000
    assert draft.source == "bluesky"


async def test_jetstream_keeps_the_mention_when_the_profile_lookup_fails():
    http, _ = stub(lambda r: httpx.Response(503))
    authors = await ProfileDirectory(http, JetstreamSettings()).resolve({"did:plc:zzz"})
    assert authors["did:plc:zzz"].handle == "did:plc:zzz"
    draft = ProfileDirectory.draft(parse_event(jet_event("Ana López", did="did:plc:zzz")), authors["did:plc:zzz"])
    assert draft.url == "https://bsky.app/profile/did:plc:zzz/post/3k1"
