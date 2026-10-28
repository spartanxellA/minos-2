import asyncio
import json
from types import SimpleNamespace

from minos_nlp import deep


class FakeMessages:
    def __init__(self, calls):
        self.calls = calls

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        n = kwargs["messages"][0]["content"].count('{"index"')
        results = [{"index": i, "relevant": True, "stance": "negative", "severe_accusation": False,
                    "topic": "ironía", "summary": "Critica al objetivo"} for i in range(n)]
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="thinking"),
                                        SimpleNamespace(type="text", text=json.dumps({"results": results}))])


def analyzer_with_fake(calls):
    a = deep.DeepAnalyzer()
    a._client = SimpleNamespace(messages=FakeMessages(calls), beta=SimpleNamespace(messages=FakeMessages(calls)))
    return a


def test_haiku_is_default_and_skips_server_fallback():
    calls: list[dict] = []
    out = asyncio.run(analyzer_with_fake(calls).analyze("Sheinbaum", ["Qué bonito gobierno, otro apagón"]))
    assert out[0]["sentiment"] == "negative" and out[0]["analyzer"] == "claude-haiku-5-5"
    assert calls[0]["model"] == "claude-haiku-5-5"
    assert "fallbacks" not in calls[0] and "betas" not in calls[0]


def test_opus_uses_server_fallback(monkeypatch):
    monkeypatch.setattr(deep, "MODEL", "claude-opus-5-5")
    calls: list[dict] = []
    asyncio.run(analyzer_with_fake(calls).analyze("Lula", ["Lula, el peor"]))
    assert calls[0]["fallbacks"] == "default"


def test_examples_are_sent_as_house_criteria():
    calls: list[dict] = []
    examples = [{"text": "Alito pierde los estribos", "sentiment": "negative"}]
    asyncio.run(analyzer_with_fake(calls).analyze("Alito", ["Alito encara a ciudadano"], examples))
    content = calls[0]["messages"][0]["content"]
    assert "Correcciones de los analistas" in content and "Alito pierde los estribos" in content
