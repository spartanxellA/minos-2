"""
Análisis profundo con Claude solo para las menciones que importan (negativas o de alto alcance):
postura hacia el objetivo, si es una acusación grave, tema y resumen de una línea.
"""
import json
import logging
import os

import anthropic

log = logging.getLogger(__name__)

MODEL = os.getenv("MINOS_CLAUDE_MODEL", "claude-opus-5-5")
EFFORT = os.getenv("MINOS_CLAUDE_EFFORT", "low")
BATCH = int(os.getenv("MINOS_CLAUDE_BATCH", "20"))

SYSTEM = (
    "Eres analista de riesgo reputacional. Recibes menciones públicas (noticias y redes sociales, casi siempre en "
    "español de México) sobre un objetivo: persona, empresa, institución, área de gobierno o país. Para cada mención "
    "decide la postura hacia ESE objetivo (no el tono general del texto), si contiene una acusación grave contra él "
    "(corrupción, delito, fraude, abuso, violencia, enriquecimiento ilícito), el tema en 1 a 3 palabras y un resumen "
    "neutral de una línea en español. Si la mención no habla realmente del objetivo (homónimo), marca relevant=false. "
    "Responde solo con el JSON pedido, un resultado por mención y en el mismo orden."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "relevant": {"type": "boolean"},
                    "stance": {"type": "string", "enum": ["negative", "neutral", "positive"]},
                    "severe_accusation": {"type": "boolean"},
                    "topic": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "required": ["index", "relevant", "stance", "severe_accusation", "topic", "summary"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


class DeepAnalyzer:
    def __init__(self) -> None:
        self.enabled = os.getenv("MINOS_CLAUDE_ENABLED", "0") == "1"
        self._client = anthropic.AsyncAnthropic() if self.enabled else None

    async def analyze(self, target: str, texts: list[str]) -> list[dict | None]:
        """Devuelve un análisis por texto, o None si no se pudo (el llamador conserva el del modelo local)."""
        if not self._client or not texts:
            return [None] * len(texts)
        out: list[dict | None] = []
        for start in range(0, len(texts), BATCH):
            out.extend(await self._batch(target, texts[start:start + BATCH]))
        return out

    async def _batch(self, target: str, texts: list[str]) -> list[dict | None]:
        payload = "\n".join(json.dumps({"index": i, "text": t}, ensure_ascii=False) for i, t in enumerate(texts))
        try:
            response = await self._client.beta.messages.create(
                model=MODEL,
                max_tokens=16000,
                system=SYSTEM,
                output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
                # Si un clasificador de seguridad rechaza el lote, la API lo reintenta en otro modelo.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                messages=[{"role": "user", "content": f"Objetivo: {target}\n\nMenciones (JSON por línea):\n{payload}"}],
            )
        except anthropic.RateLimitError:
            log.warning("Claude: límite de tasa; el lote se queda con el análisis local")
            return [None] * len(texts)
        except anthropic.APIStatusError as e:
            log.warning("Claude respondió %s: %s", e.status_code, e.message)
            return [None] * len(texts)
        except anthropic.APIConnectionError:
            log.warning("Claude no disponible (conexión)")
            return [None] * len(texts)

        if response.stop_reason in ("refusal", "max_tokens"):
            log.warning("Claude no completó el lote (stop_reason=%s)", response.stop_reason)
            return [None] * len(texts)
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            results = json.loads(text)["results"]
        except (json.JSONDecodeError, KeyError, TypeError):
            log.warning("Respuesta de Claude no es JSON válido")
            return [None] * len(texts)

        by_index = {r["index"]: r for r in results if isinstance(r, dict) and "index" in r}
        out: list[dict | None] = []
        for i in range(len(texts)):
            r = by_index.get(i)
            out.append(None if r is None else {
                "sentiment": r["stance"],
                "severe_accusation": bool(r["severe_accusation"]) and bool(r["relevant"]),
                "topic": r["topic"] or None,
                "summary": r["summary"] or None,
                "relevant": bool(r["relevant"]),
                "analyzer": MODEL,
            })
        return out
