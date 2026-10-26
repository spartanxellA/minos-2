"""Sentimiento para el 100% del volumen: modelo multilingüe local si está instalado, si no el diccionario."""
import logging
import os

from . import lexicon

log = logging.getLogger(__name__)

MODEL_NAME = os.getenv("MINOS_SENTIMENT_MODEL", "cardiffnlp/twitter-xlm-roberta-base-sentiment")


class SentimentModel:
    def __init__(self) -> None:
        self._pipe = None
        if os.getenv("MINOS_USE_TRANSFORMERS", "0") == "1":
            try:
                from transformers import pipeline  # type: ignore

                self._pipe = pipeline("sentiment-analysis", model=MODEL_NAME, truncation=True)
                log.info("Modelo de sentimiento cargado: %s", MODEL_NAME)
            except Exception:  # noqa: BLE001 - sin modelo seguimos con el diccionario
                log.exception("No se pudo cargar %s; se usa el diccionario", MODEL_NAME)

    @property
    def name(self) -> str:
        return MODEL_NAME if self._pipe else "lexicon"

    def analyze(self, texts: list[str]) -> list[dict]:
        base = [lexicon.analyze(t) for t in texts]
        if not self._pipe:
            return base
        for item, pred in zip(base, self._pipe(texts, batch_size=32)):
            label = pred["label"].lower()
            sentiment = "negative" if label.startswith("neg") else "positive" if label.startswith("pos") else "neutral"
            sign = {"negative": -1, "positive": 1, "neutral": 0}[sentiment]
            # El diccionario sigue marcando acusaciones graves; el modelo decide el tono.
            item.update(sentiment=sentiment, score=round(sign * float(pred["score"]), 3), analyzer=self.name)
        return base
