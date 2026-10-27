"""Cálculo de riesgo: cuestionario (fórmula de minOS 1.6), medios, Índice de Riesgo Reputacional y alertas."""
import math
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from .mentions import Sentiment


class RiskLevel(StrEnum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


# Umbrales heredados de minOS 1.x: ≤ 25 bajo, ≤ 50 medio, > 50 alto.
LOW_MAX = 25
MEDIUM_MAX = 50

LEVEL_LABEL = {RiskLevel.LOW: "Riesgo bajo", RiskLevel.MEDIUM: "Riesgo medio", RiskLevel.HIGH: "Riesgo alto"}
LEVEL_COLOR = {RiskLevel.LOW: "#2E7D32", RiskLevel.MEDIUM: "#DAD500", RiskLevel.HIGH: "#F44336"}


def level_for(score: float) -> RiskLevel:
    if score <= LOW_MAX:
        return RiskLevel.LOW
    if score <= MEDIUM_MAX:
        return RiskLevel.MEDIUM
    return RiskLevel.HIGH


# --- Cuestionario ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class SectionAnswers:
    """Respuestas de una sección: peso de la sección y el peso de cada respuesta (1 bueno, 2 regular, 3 malo)."""

    section_id: str
    section_weight: float
    total_questions: int
    answer_weights: Sequence[float]


@dataclass(frozen=True)
class SectionRisk:
    section_id: str
    value: int
    level: RiskLevel


@dataclass(frozen=True)
class SurveyRiskResult:
    score: float
    level: RiskLevel
    sections: list[SectionRisk]


def section_value(section: SectionAnswers) -> int:
    """v = round((Σ pesos − n) × 100 / 2n), idéntico a risk-survey.ts de minOS 1.6."""
    # En 1.6 una sección sin preguntas cuenta como 1 (COALESCE(COUNT(...), 1)).
    n = max(section.total_questions, 1)
    raw = (sum(section.answer_weights) - n) * 100 / (n * 2.0)
    # Math.round de JavaScript redondea .5 hacia arriba; round() de Python redondea al par.
    return math.floor(raw + 0.5)


def survey_risk(sections: Iterable[SectionAnswers]) -> SurveyRiskResult:
    results = []
    score = 0.0
    for section in sections:
        value = section_value(section)
        score += value * section.section_weight
        results.append(SectionRisk(section.section_id, value, level_for(value)))
    return SurveyRiskResult(score, level_for(score), results)


# --- Medios ---------------------------------------------------------------------------------------


class ScoredMention(Protocol):
    id: uuid.UUID
    sentiment: Sentiment
    is_severe_accusation: bool
    author_followers: int
    author_handle: str
    source: str
    text: str

    @property
    def interactions(self) -> int: ...


@dataclass(frozen=True)
class VolumeBaseline:
    """Volumen histórico del objetivo por ventana, para detectar picos."""

    mean_per_window: float
    std_dev_per_window: float

    @classmethod
    def from_history(cls, counts: Sequence[int]) -> "VolumeBaseline":
        if not counts:
            return cls(0, 0)
        mean = sum(counts) / len(counts)
        variance = sum((c - mean) ** 2 for c in counts) / len(counts)
        return cls(mean, math.sqrt(variance))


@dataclass(frozen=True)
class MediaRiskWeights:
    negativity: float = 0.5
    severity: float = 0.3
    volume: float = 0.2


@dataclass(frozen=True)
class MediaRiskResult:
    score: float
    negativity: float
    severity: float
    volume_anomaly: float
    volume_z: float
    mention_count: int
    top_drivers: list[uuid.UUID] = field(default_factory=list)


def reach_weight(m: ScoredMention) -> float:
    """Peso por alcance: 1 + ln(1 + seguidores + interacciones)."""
    return 1 + math.log(1 + max(0, m.author_followers) + max(0, m.interactions))


def media_risk(
    window: Sequence[ScoredMention], baseline: VolumeBaseline | None, weights: MediaRiskWeights = MediaRiskWeights()
) -> MediaRiskResult:
    """M = 100 × (0.5 N + 0.3 S + 0.2 V).

    N negatividad ponderada por alcance, S proporción de acusaciones graves, V volumen anómalo.
    Sin línea base (objetivo nuevo) el volumen no suma riesgo.
    """
    if not window:
        return MediaRiskResult(0, 0, 0, 0, 0, 0)

    total_reach = negative_reach = 0.0
    for m in window:
        w = reach_weight(m)
        total_reach += w
        if m.sentiment == Sentiment.NEGATIVE:
            negative_reach += w
    negativity = negative_reach / total_reach if total_reach > 0 else 0
    severity = sum(1 for m in window if m.is_severe_accusation) / len(window)

    z = 0.0 if baseline is None else (len(window) - baseline.mean_per_window) / max(baseline.std_dev_per_window, 1)
    volume = min(max(z / 3, 0), 1)

    score = 100 * (weights.negativity * negativity + weights.severity * severity + weights.volume * volume)
    drivers = sorted(
        (m for m in window if m.sentiment == Sentiment.NEGATIVE or m.is_severe_accusation),
        key=lambda m: reach_weight(m) * (2 if m.is_severe_accusation else 1),
        reverse=True,
    )[:5]
    return MediaRiskResult(min(max(score, 0), 100), negativity, severity, volume, z, len(window), [m.id for m in drivers])


# --- Índice ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class IndexWeights:
    media: float = 0.6
    survey: float = 0.4


@dataclass(frozen=True)
class ReputationIndexResult:
    score: float
    level: RiskLevel
    media_score: float
    survey_score: float | None


def reputation_index(media_score: float, survey_score: float | None, weights: IndexWeights = IndexWeights()) -> ReputationIndexResult:
    """IRR de 0 a 100. Con cuestionario: 0.6 M + 0.4 C; sin cuestionario (empresas, gobierno, países): IRR = M."""
    if survey_score is None:
        score = media_score
    else:
        score = (weights.media * media_score + weights.survey * survey_score) / (weights.media + weights.survey)
    score = round(min(max(score, 0), 100), 2)
    return ReputationIndexResult(score, level_for(score), media_score, survey_score)


# --- Alertas --------------------------------------------------------------------------------------


class AlertKind(StrEnum):
    INDEX_JUMP = "IndexJump"
    NEGATIVE_SPIKE = "NegativeSpike"
    SEVERE_HIGH_REACH_MENTION = "SevereHighReachMention"


@dataclass(frozen=True)
class RiskAlert:
    kind: AlertKind
    title: str
    message: str
    mention_id: uuid.UUID | None = None


INDEX_JUMP_POINTS = 15
SPIKE_Z = 3
SPIKE_NEGATIVITY = 0.5
HIGH_REACH_FOLLOWERS = 100_000


def _truncate(s: str, limit: int) -> str:
    return s if len(s) <= limit else s[: limit - 1] + "…"


def evaluate_alerts(
    previous_index_24h_ago: float | None, current_index: float, media: MediaRiskResult, new_mentions: Iterable[ScoredMention]
) -> list[RiskAlert]:
    """Reglas que reemplazan la del 75% de minOS 1.x."""
    alerts = []
    if previous_index_24h_ago is not None and current_index - previous_index_24h_ago >= INDEX_JUMP_POINTS:
        alerts.append(RiskAlert(
            AlertKind.INDEX_JUMP, "Cambio de tendencia",
            f"El índice subió {current_index - previous_index_24h_ago:.0f} puntos en 24 horas "
            f"({previous_index_24h_ago:.0f} → {current_index:.0f}).",
        ))
    if media.volume_z >= SPIKE_Z and media.negativity > SPIKE_NEGATIVITY:
        alerts.append(RiskAlert(
            AlertKind.NEGATIVE_SPIKE, "Pico de menciones negativas",
            f"El volumen está {media.volume_z:.1f} desviaciones arriba de lo normal y {media.negativity:.0%} es negativo.",
        ))
    for m in new_mentions:
        if m.is_severe_accusation and m.author_followers >= HIGH_REACH_FOLLOWERS:
            alerts.append(RiskAlert(
                AlertKind.SEVERE_HIGH_REACH_MENTION, "Acusación de alto alcance",
                f"{m.author_handle} ({m.author_followers:,} seguidores) en {m.source}: {_truncate(m.text, 140)}",
                m.id,
            ))
    return alerts


# --- Listas negras --------------------------------------------------------------------------------

# Una sanción confirmada (OFAC, ONU, UE, Reino Unido) deja el índice en riesgo alto sin importar lo que digan las redes.
SANCTIONS_FLOOR = 85
# Puntos que suma una coincidencia confirmada de cada tipo de lista. Ser PEP no es negativo, solo expone más.
WATCHLIST_POINTS = {"sanctions": 20, "tax": 20, "debarment": 20, "other": 20, "pep": 10}
# Situaciones que aún no son definitivas (SAT 69-B "Presunto"): pesan la mitad.
TENTATIVE_STATUS = ("presunto",)


@dataclass(frozen=True)
class WatchlistHit:
    category: str
    status: str | None = None


def watchlist_adjust(score: float, hits: Iterable[WatchlistHit]) -> float:
    """Índice después de sumar las coincidencias confirmadas: la mayor de cada tipo de lista, con piso por sanciones."""
    best: dict[str, float] = {}
    sanctioned = False
    for h in hits:
        points = WATCHLIST_POINTS.get(h.category, WATCHLIST_POINTS["other"])
        if h.status and h.status.strip().lower().startswith(TENTATIVE_STATUS):
            points /= 2
        else:
            sanctioned = sanctioned or h.category == "sanctions"
        best[h.category] = max(best.get(h.category, 0), points)
    adjusted = min(score + sum(best.values()), 100)
    if sanctioned:
        adjusted = max(adjusted, SANCTIONS_FLOOR)
    return round(adjusted, 2)
