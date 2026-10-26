import pytest

from minos.config import DATA_DIR
from minos.domain.risk import RiskLevel
from minos.surveys import SurveyCatalog

CATALOG = SurveyCatalog(DATA_DIR / "surveys.json")


def test_loads_both_legacy_surveys_with_107_questions():
    assert len(CATALOG.all) == 2
    assert sum(len(sec.questions) for s in CATALOG.all for sec in s.sections) == 107
    assert sum(sec.weight for sec in CATALOG.find("RASurvey").sections) == pytest.approx(1.0)


def test_worst_answers_everywhere_give_100_and_best_give_0():
    survey = CATALOG.find("RASurvey")
    questions = [q for s in survey.sections for q in s.questions]
    worst = {q.id: max(q.options, key=lambda o: o.weight).value for q in questions}
    best = {q.id: min(q.options, key=lambda o: o.weight).value for q in questions}
    assert CATALOG.score(survey, worst).score == pytest.approx(100)
    assert CATALOG.score(survey, best).score == pytest.approx(0)
    assert CATALOG.score(survey, worst).level == RiskLevel.HIGH


def test_profile_survey_is_not_scored():
    assert CATALOG.score(CATALOG.find("PDSurvey"), {}) is None
