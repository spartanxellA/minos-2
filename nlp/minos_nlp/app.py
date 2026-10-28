"""API del servicio de análisis. La consume la API de minOS (backend/minos/analysis.py) en POST /v1/analyze."""
import logging
import os
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .deep import DeepAnalyzer
from .sentiment import SentimentModel

logging.basicConfig(level=logging.INFO)

# Alcance (seguidores + interacciones) a partir del cual una mención positiva o neutral también va a Claude.
HIGH_REACH = int(os.getenv("MINOS_HIGH_REACH", "50000"))

app = FastAPI(title="minOS NLP", version="0.1.0")
sentiment_model = SentimentModel()
deep = DeepAnalyzer()


class Item(BaseModel):
    text: str
    language: str | None = None
    reach: int = 0


class Example(BaseModel):
    text: str = Field(max_length=2000)
    sentiment: Literal["negative", "neutral", "positive"]


class AnalyzeRequest(BaseModel):
    target: str
    items: list[Item] = Field(default_factory=list, max_length=500)
    # Correcciones de los analistas para este objetivo; Claude las toma como criterio.
    examples: list[Example] = Field(default_factory=list, max_length=30)


class Result(BaseModel):
    sentiment: str
    score: float
    severe_accusation: bool = Field(serialization_alias="severeAccusation")
    topic: str | None = None
    summary: str | None = None
    analyzer: str


class AnalyzeResponse(BaseModel):
    results: list[Result]


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "sentiment": sentiment_model.name, "claude": deep.enabled}


@app.post("/v1/analyze", response_model=AnalyzeResponse, response_model_by_alias=True)
async def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    texts = [i.text for i in req.items]
    base = sentiment_model.analyze(texts)

    # Solo lo que importa pasa por Claude: negativas, posibles acusaciones, dudosas (señales mezcladas o débiles,
    # donde el diccionario más se equivoca) o de alto alcance.
    picked = [i for i, (item, b) in enumerate(zip(req.items, base))
              if b["sentiment"] == "negative" or b["severe_accusation"] or b.get("ambiguous")
              or item.reach >= HIGH_REACH]
    deep_results = await deep.analyze(req.target, [texts[i] for i in picked], [e.model_dump() for e in req.examples])
    for i, d in zip(picked, deep_results):
        if d is None:
            continue
        sign = {"negative": -1.0, "positive": 1.0, "neutral": 0.0}[d["sentiment"]]
        base[i].update(
            sentiment=d["sentiment"] if d["relevant"] else "neutral",
            score=sign * max(abs(base[i]["score"]), 0.5) if d["relevant"] else 0.0,
            severe_accusation=d["severe_accusation"],
            topic=d["topic"],
            summary=d["summary"],
            analyzer=d["analyzer"],
        )
    return AnalyzeResponse(results=[Result(**b) for b in base])
