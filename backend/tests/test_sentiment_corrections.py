"""Un analista corrige el sentimiento de una mención: cuenta en el índice, queda en la bitácora y se manda como
ejemplo al análisis de las menciones nuevas."""
from datetime import UTC, datetime, timedelta

from test_api import client, create_target  # noqa: F401  (fixture)

from minos.analysis import LexiconAnalyzer
from minos.config import IngestionSettings
from minos.domain.mentions import AuthorInfo, MentionDraft
from minos.pipeline import IngestionWorker


class OnePost:
    source = "facebook"
    is_configured = True
    poll_interval = timedelta(0)

    def __init__(self, text: str, external_id: str = "p1") -> None:
        self.text, self.external_id = text, external_id

    async def fetch(self, target, cursor):
        yield MentionDraft("facebook", self.external_id, f"https://facebook.com/{self.external_id}", AuthorInfo("Laura"),
                           datetime.now(UTC), self.text, own_channel=True)


class RecordingAnalyzer(LexiconAnalyzer):
    def __init__(self) -> None:
        self.examples: list = []

    async def analyze(self, drafts, target_name, examples=()):
        self.examples.append(list(examples))
        return await super().analyze(drafts, target_name, examples)


def ingest(client, connector, analyzer=None):
    app = client.app
    worker = IngestionWorker(app.state.db, [connector], analyzer or LexiconAnalyzer(), app.state.bus, IngestionSettings())
    client.portal.call(worker.run_once)


def test_correction_changes_sentiment_index_and_audit(client):
    t = create_target(client)
    ingest(client, OnePost("Qué bonito gobierno tenemos"))
    [m] = client.get(f"/api/targets/{t['id']}/mentions").json()
    assert m["sentiment"] != "negative" and m["corrected"] is False

    r = client.post(f"/api/mentions/{m['id']}/sentiment", json={"sentiment": "negative"})

    assert r.status_code == 200, r.text
    out = r.json()
    assert out["sentiment"] == "negative" and out["corrected"] is True
    assert out["originalSentiment"] == m["sentiment"] and out["score"] <= -0.5
    [listed] = client.get(f"/api/targets/{t['id']}/mentions", params={"sentiment": "negative"}).json()
    assert listed["id"] == m["id"]
    assert client.get(f"/api/targets/{t['id']}/risk/latest").json()["negative"] == 1

    # Una segunda corrección conserva lo que dijo el análisis automático la primera vez.
    again = client.post(f"/api/mentions/{m['id']}/sentiment", json={"sentiment": "neutral"}).json()
    assert again["originalSentiment"] == m["sentiment"] and again["score"] == 0

    [event] = client.get("/api/audit", params={"action": "mention.sentiment_corrected", "q": ""}).json()["events"][:1]
    assert event["changes"] == {"sentiment": ["negative", "neutral"]}
    assert event["detail"]["mentionId"] == m["id"]


def test_correction_rejects_unknown_values_and_mentions(client):
    create_target(client)
    assert client.post("/api/mentions/00000000-0000-0000-0000-000000000000/sentiment",
                       json={"sentiment": "negative"}).status_code == 404
    ingest(client, OnePost("Ana López presenta informe"))
    [m] = client.get(f"/api/targets/{client.get('/api/targets').json()[0]['id']}/mentions").json()
    assert client.post(f"/api/mentions/{m['id']}/sentiment", json={"sentiment": "furioso"}).status_code == 422


def test_corrections_are_sent_as_examples_to_the_analyzer(client):
    t = create_target(client)
    ingest(client, OnePost("Qué bonito gobierno tenemos"))
    [m] = client.get(f"/api/targets/{t['id']}/mentions").json()
    client.post(f"/api/mentions/{m['id']}/sentiment", json={"sentiment": "negative"})

    analyzer = RecordingAnalyzer()
    ingest(client, OnePost("Qué bonita reforma, otra vez sin agua", "p2"), analyzer)

    assert analyzer.examples == [[{"text": "Qué bonito gobierno tenemos", "sentiment": "negative"}]]
