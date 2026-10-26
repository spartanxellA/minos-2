"""Cuestionarios migrados de minOS 1.6 (data/surveys.json): riesgo (RASurvey, puntúa) y perfil (PDSurvey)."""
import json
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel

from .domain.risk import SectionAnswers, SurveyRiskResult, survey_risk


# Tipos de minOS 1.6 cuya respuesta es una sola de las opciones.
SINGLE_CHOICE = {"RAD", "CBO", "YN"}


class SurveyOption(BaseModel):
    value: str
    label: str
    weight: float | None = None


class SurveyQuestion(BaseModel):
    id: str
    number: int
    text: str
    subtext: str | None = None
    type: str
    required: bool
    options: list[SurveyOption]


class SurveySection(BaseModel):
    id: str
    name: str
    theme: str
    color: str
    weight: float
    order: int
    description: str
    questions: list[SurveyQuestion]


class SurveyDefinition(BaseModel):
    id: str
    name: str
    description: str
    scored: bool
    sections: list[SurveySection]


class SurveyCatalog:
    def __init__(self, path: Path) -> None:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self._surveys = {s["id"]: SurveyDefinition.model_validate(s) for s in data["surveys"]}

    @property
    def all(self) -> list[SurveyDefinition]:
        return list(self._surveys.values())

    def find(self, survey_id: str) -> SurveyDefinition | None:
        return self._surveys.get(survey_id)

    @staticmethod
    def problems(survey: SurveyDefinition, answers: Mapping[str, str]) -> list[str]:
        """Errores de un envío: preguntas que no existen, opciones inválidas y, si puntúa, obligatorias sin contestar.

        En un cuestionario que puntúa, una pregunta sin contestar baja la sección por debajo de 0 (la fórmula divide
        entre todas las preguntas), así que se exigen todas como en minOS 1.6."""
        questions = {q.id: q for section in survey.sections for q in section.questions}
        out = [f"{qid}: pregunta desconocida" for qid in answers if qid not in questions]
        for qid, value in answers.items():
            q = questions.get(qid)
            if q is not None and q.type in SINGLE_CHOICE and q.options and value not in {o.value for o in q.options}:
                out.append(f"{qid}: opción inválida {value!r}")
        if survey.scored:
            out += [f"{q.id}: falta la respuesta" for q in questions.values() if q.required and not answers.get(q.id)]
        return out

    @staticmethod
    def score(survey: SurveyDefinition, answers: Mapping[str, str]) -> SurveyRiskResult | None:
        """Puntúa con la fórmula de minOS 1.6. None si el cuestionario no puntúa (perfil)."""
        if not survey.scored:
            return None
        sections = []
        for section in survey.sections:
            weights = []
            for q in section.questions:
                chosen = answers.get(q.id)
                option = next((o for o in q.options if o.value == chosen), None)
                if option is not None and option.weight is not None:
                    weights.append(option.weight)
            sections.append(SectionAnswers(section.id, section.weight, len(section.questions), weights))
        return survey_risk(sections)
