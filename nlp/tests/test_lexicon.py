"""Casos reales de política MX/LatAm que el diccionario anterior dejaba en Neutro."""
import pytest

from minos_nlp import lexicon

NEGATIVE = [
    "Sheinbaum no ha hecho nada por la seguridad, el país está a la deriva",
    "La presidenta no es nada transparente con el Tren Maya",
    "#NarcoPresidenta otra vez protegiendo a sus amigos 🤡",
    "Lula es un ratero y todos lo saben",
    "Bonito discurso, pero los muertos siguen aumentando",
    "Claudia Sheinbaum se burla de las madres buscadoras",
    "Lula, el peor presidente que ha tenido Brasil 👎👎",
    "Cae la aprobación de Sheinbaum por el desabasto de medicinas",
    "No, Sheinbaum es corrupta como todos",
    "Pinche gobierno inútil 😡",
    "Aunque es honesta, su gabinete es totalmente inepto",
    "Abuchean a Lula en el estadio",
    "Hartos de las promesas de la 4T #FueraMorena",
]
NEUTRAL = [
    "La presidenta se reunió con empresarios en Monterrey",
    "Lula viaja a China para la cumbre de los BRICS",
    "Sheinbaum anuncia lucha contra la corrupción",
]
POSITIVE = [
    "Gran trabajo de la presidenta con el programa de becas 👏",
    "Todo mi apoyo a Claudia Sheinbaum, vamos bien",
    "Sin corrupción y con resultados, así se gobierna 💪",
]


@pytest.mark.parametrize("text", NEGATIVE)
def test_negative_posts(text):
    assert lexicon.analyze(text)["sentiment"] == "negative"


@pytest.mark.parametrize("text", NEUTRAL)
def test_neutral_posts(text):
    assert lexicon.analyze(text)["sentiment"] == "neutral"


@pytest.mark.parametrize("text", POSITIVE)
def test_positive_posts(text):
    assert lexicon.analyze(text)["sentiment"] == "positive"


def test_negation_flips_and_softens():
    assert lexicon.analyze("No es bueno")["sentiment"] == "negative"
    # "no es malo" solo es tibiamente positivo
    assert 0 < lexicon.analyze("No es malo")["score"] < lexicon.analyze("Es bueno")["score"]


def test_intensifier_raises_weight():
    assert lexicon.analyze("Es muy mala")["score"] < lexicon.analyze("Es mala")["score"]


def test_stems_cover_inflections():
    for word in ("corrupto", "corruptas", "rateros", "ineptos", "mentirosa"):
        assert lexicon.word_polarity(word) < 0, word


def test_but_clause_weighs_more():
    assert lexicon.analyze("Es honesto pero muy inepto")["sentiment"] == "negative"


def test_severe_accusation_skipped_when_negated():
    assert lexicon.analyze("Sin corrupción y con resultados")["severe_accusation"] is False
    assert lexicon.analyze("Detenido por lavado de dinero")["severe_accusation"] is True


def test_mixed_signals_marked_ambiguous():
    assert lexicon.analyze("Lula no es malo, solo le falta apoyo en el congreso")["ambiguous"] is True
    assert lexicon.analyze("Reunión el martes")["ambiguous"] is False
