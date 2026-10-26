import uuid
from dataclasses import dataclass

import pytest

from minos.domain.mentions import Sentiment
from minos.domain.risk import (
    AlertKind, MediaRiskResult, RiskLevel, SectionAnswers, VolumeBaseline, evaluate_alerts, level_for, media_risk,
    reputation_index, section_value, survey_risk,
)


@dataclass
class M:
    sentiment: Sentiment
    author_followers: int = 0
    is_severe_accusation: bool = False
    id: uuid.UUID = None
    author_handle: str = "@a"
    source: str = "test"
    text: str = "t"
    interactions: int = 0

    def __post_init__(self):
        self.id = self.id or uuid.uuid4()


# --- Cuestionario (fórmula de minOS 1.6) ---


def test_all_good_answers_give_zero_risk():
    assert section_value(SectionAnswers("FamFac", 0.2, 3, [1, 1, 1])) == 0


def test_all_bad_answers_give_full_risk():
    assert section_value(SectionAnswers("FamFac", 0.2, 4, [3, 3, 3, 3])) == 100


def test_matches_legacy_formula_and_rounds_half_up_like_javascript():
    # (2+2+1 − 3) × 100 / 6 = 33.33 → 33 ; (3+1 − 2) × 100 / 4 = 50
    assert section_value(SectionAnswers("a", 1, 3, [2, 2, 1])) == 33
    assert section_value(SectionAnswers("b", 1, 2, [3, 1])) == 50
    # (1+1+1+2 − 4) × 100 / 8 = 12.5 → 13 (Math.round de JS), no 12 (redondeo al par de Python)
    assert section_value(SectionAnswers("c", 1, 4, [1, 1, 1, 2])) == 13


def test_total_is_weighted_sum_with_legacy_thresholds():
    result = survey_risk([
        SectionAnswers("PerFac", 0.30, 2, [3, 3]),  # 100
        SectionAnswers("FamFac", 0.20, 2, [1, 1]),  # 0
        SectionAnswers("SocFac", 0.20, 2, [2, 2]),  # 50
        SectionAnswers("EduFac", 0.15, 2, [1, 1]),  # 0
        SectionAnswers("ProFac", 0.15, 2, [1, 1]),  # 0
    ])
    assert result.score == pytest.approx(40)
    assert result.level == RiskLevel.MEDIUM
    assert result.sections[0].level == RiskLevel.HIGH


@pytest.mark.parametrize("score,expected", [
    (25, RiskLevel.LOW), (25.01, RiskLevel.MEDIUM), (50, RiskLevel.MEDIUM), (50.01, RiskLevel.HIGH),
])
def test_thresholds_are_inclusive_like_minos_1(score, expected):
    assert level_for(score) == expected


# --- Medios ---


def test_empty_window_has_no_risk():
    assert media_risk([], VolumeBaseline(10, 2)).score == 0


def test_high_reach_criticism_weighs_more_than_many_small_accounts():
    window = [M(Sentiment.NEGATIVE, 2_000_000)] + [M(Sentiment.POSITIVE, 10) for _ in range(5)]
    r = media_risk(window, VolumeBaseline(6, 2))
    # 1 de 6 menciones (17%) es negativa, pero por alcance pesa casi tanto como las otras cinco juntas.
    assert 0.4 <= r.negativity <= 0.6


def test_score_combines_negativity_severity_and_volume():
    window = [M(Sentiment.NEGATIVE, is_severe_accusation=i < 15) for i in range(30)]
    r = media_risk(window, VolumeBaseline(mean_per_window=3, std_dev_per_window=1))
    # N = 1, S = 0.5, V = 1 → 100 × (0.5 + 0.15 + 0.2) = 85
    assert r.score == pytest.approx(85)
    assert len(r.top_drivers) == 5


def test_normal_volume_adds_no_anomaly():
    window = [M(Sentiment.NEUTRAL) for _ in range(10)]
    r = media_risk(window, VolumeBaseline.from_history([10, 11, 9, 10]))
    assert r.volume_anomaly == 0
    assert r.score == 0


def test_without_baseline_volume_does_not_add_risk():
    r = media_risk([M(Sentiment.NEUTRAL) for _ in range(50)], baseline=None)
    assert r.volume_anomaly == 0
    assert r.score == 0


# --- Índice y alertas ---


def test_combines_media_and_survey_with_default_weights():
    r = reputation_index(media_score=50, survey_score=25)
    assert r.score == 40
    assert r.level == RiskLevel.MEDIUM


def test_without_survey_index_equals_media_risk():
    assert reputation_index(72.5, None).score == 72.5


def test_jump_of_15_points_in_24h_raises_trend_alert():
    media = MediaRiskResult(60, 0.4, 0, 0, 0, 10)
    alerts = evaluate_alerts(previous_index_24h_ago=40, current_index=56, media=media, new_mentions=[])
    assert any(a.kind == AlertKind.INDEX_JUMP for a in alerts)


def test_small_change_raises_nothing():
    assert evaluate_alerts(40, 44, MediaRiskResult(30, 0.2, 0, 0, 1, 10), []) == []


def test_severe_mention_from_big_account_raises_alert():
    mention = M(Sentiment.NEGATIVE, author_followers=250_000, is_severe_accusation=True)
    alerts = evaluate_alerts(None, 30, MediaRiskResult(30, 0.2, 0.1, 0, 0, 10), [mention])
    assert [a.kind for a in alerts] == [AlertKind.SEVERE_HIGH_REACH_MENTION]
    assert alerts[0].mention_id == mention.id
