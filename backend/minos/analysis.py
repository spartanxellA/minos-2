"""Análisis de menciones: servicio de NLP (carpeta nlp/) con el diccionario como respaldo."""
import logging
from collections.abc import Sequence
from typing import Protocol

import httpx
from minos_nlp import lexicon

from .domain.mentions import MentionAnalysis, MentionDraft, Sentiment

log = logging.getLogger(__name__)

_SENTIMENT = {"negative": Sentiment.NEGATIVE, "positive": Sentiment.POSITIVE, "neutral": Sentiment.NEUTRAL}


class MentionAnalyzer(Protocol):
    async def analyze(
        self, drafts: Sequence[MentionDraft], target_name: str, examples: Sequence[dict] = (),
    ) -> list[MentionAnalysis]:
        """`examples`: correcciones de los analistas ({"text", "sentiment"}) que guían al análisis profundo."""
        ...


def _from_dict(d: dict) -> MentionAnalysis:
    return MentionAnalysis(
        sentiment=_SENTIMENT.get(d.get("sentiment", ""), Sentiment.NEUTRAL),
        score=float(d.get("score", 0)),
        severe_accusation=bool(d.get("severeAccusation", d.get("severe_accusation", False))),
        topic=d.get("topic"),
        summary=d.get("summary"),
        analyzer=d.get("analyzer") or "nlp",
    )


class LexiconAnalyzer:
    """Diccionario en español, el mismo del servicio de NLP. Deliberadamente simple: es el respaldo."""

    async def analyze(
        self, drafts: Sequence[MentionDraft], target_name: str, examples: Sequence[dict] = (),
    ) -> list[MentionAnalysis]:
        return [_from_dict(lexicon.analyze(d.text)) for d in drafts]


class NlpServiceAnalyzer:
    """Llama a POST {nlp_url}/v1/analyze; si falla o no está configurado, usa el diccionario."""

    def __init__(self, http: httpx.AsyncClient, base_url: str, fallback: LexiconAnalyzer | None = None) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._fallback = fallback or LexiconAnalyzer()

    async def analyze(
        self, drafts: Sequence[MentionDraft], target_name: str, examples: Sequence[dict] = (),
    ) -> list[MentionAnalysis]:
        if not self._base_url or not drafts:
            return await self._fallback.analyze(drafts, target_name)
        payload = {
            "target": target_name,
            "items": [
                {"text": d.text, "language": d.language, "reach": d.author.followers + d.engagement.interactions}
                for d in drafts
            ],
            "examples": list(examples),
        }
        try:
            response = await self._http.post(f"{self._base_url}/v1/analyze", json=payload, timeout=60)
            response.raise_for_status()
            results = response.json().get("results") or []
            if len(results) == len(drafts):
                return [_from_dict(r) for r in results]
            log.warning("El servicio de NLP devolvió %s resultados para %s textos", len(results), len(drafts))
        except (httpx.HTTPError, ValueError) as ex:
            log.warning("Servicio de NLP no disponible, se usa el diccionario: %s", ex)
        return await self._fallback.analyze(drafts, target_name)
