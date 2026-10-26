"""Analizador de respaldo en español por diccionario (la API lo reutiliza como respaldo si este servicio no responde)."""
import re
import unicodedata

POSITIVE = {
    "excelente", "bueno", "buena", "logro", "exito", "gracias", "felicidades", "apoyo", "mejor", "reconocimiento",
    "honesto", "transparente", "eficiente", "avance", "beneficio", "aplauso", "orgullo", "positivo", "gano", "gana",
}
NEGATIVE = {
    "malo", "mala", "pesimo", "fracaso", "critica", "criticas", "escandalo", "mentira", "renuncia", "protesta",
    "denuncia", "investigacion", "polemica", "negligencia", "crisis", "multa", "sancion", "abuso", "ineficiente",
    "verguenza",
}
SEVERE = [
    "corrupcion", "fraude", "soborno", "lavado", "desvio", "peculado", "delito", "detenido", "acoso", "narco",
    "enriquecimiento ilicito", "malversacion", "extorsion", "trafico de influencias", "nepotismo",
]


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.lower())
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return " " + " ".join(re.sub(r"[^\w@#]+", " ", stripped).split()) + " "


def analyze(text: str) -> dict:
    t = normalize(text)
    words = set(t.split())
    pos = len(words & POSITIVE)
    neg = len(words & NEGATIVE)
    severe = [w for w in SEVERE if f" {w} " in t]
    neg += 2 * len(severe)
    score = 0.0 if pos + neg == 0 else (pos - neg) / (pos + neg)
    sentiment = "negative" if score <= -0.2 else "positive" if score >= 0.2 else "neutral"
    return {
        "sentiment": sentiment,
        "score": round(score, 3),
        "severe_accusation": bool(severe),
        "topic": severe[0] if severe else None,
        "summary": None,
        "analyzer": "lexicon",
    }
