import pytest

from minos.connectors.query import build_query
from minos.domain.mentions import fingerprint
from minos.domain.targets import MonitoredTarget, is_relevant

TARGET = MonitoredTarget(
    name="Ana López", aliases=["Secretaria López"], excluded_terms=["López Obrador"], handles={"x": "@analopez"}
)


@pytest.mark.parametrize("text,expected", [
    ("Critican a ANA LOPEZ por el presupuesto", True),
    ("La secretaria lópez respondió", True),
    ("Responde @analopez a periodistas", True),
    ("Mariana López ganó el torneo", False),
    ("Ana López y López Obrador se reunieron", False),
    ("Analopez es una palabra inventada", False),
])
def test_detects_real_mentions_and_skips_homonyms(text, expected):
    assert is_relevant(TARGET, text) is expected


def test_retweets_and_different_links_share_fingerprint():
    a = fingerprint("Acusan a Ana López de fraude https://t.co/abc")
    b = fingerprint("RT @medio: Acusan a ana lopez de fraude https://t.co/xyz")
    assert a == b


def test_different_text_has_different_fingerprint():
    assert fingerprint("uno") != fingerprint("dos")


def test_builds_or_query_with_keywords_and_exclusions():
    t = MonitoredTarget(name="Ana López", aliases=["ALópez"], keywords=["secretaria"], excluded_terms=["López Obrador"])
    assert build_query(t) == '("Ana López" OR ALópez) (secretaria) -"López Obrador"'
