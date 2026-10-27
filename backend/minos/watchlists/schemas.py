"""Contratos JSON de las listas negras."""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from .. import db
from ..schemas import Camel
from .sources import CATEGORY_LABEL

# Siempre se muestra junto al resultado.
DISCLAIMER = ("Resultado informativo: una coincidencia de nombre no prueba que sea la misma persona o empresa. "
              "Verifique la identidad con la fuente oficial antes de tomar una decisión.")


class MatchOut(Camel):
    id: int
    target_id: uuid.UUID
    target_name: str | None = None
    source: str
    source_name: str
    category: str
    category_label: str
    listed_name: str
    matched_name: str
    score: float
    strength: str
    reasons: list[str]
    entry: dict
    status: str
    active: bool
    first_seen_at: datetime
    last_seen_at: datetime
    reviewed_at: datetime | None
    reviewed_by_email: str | None
    review_note: str | None

    @classmethod
    def of(cls, m: db.ScreeningMatch, target_name: str | None = None) -> "MatchOut":
        return cls(
            id=m.id, target_id=m.target_id, target_name=target_name, source=m.source, source_name=m.source_name,
            category=m.category, category_label=CATEGORY_LABEL.get(m.category, m.category), listed_name=m.listed_name,
            matched_name=m.matched_name, score=m.score, strength=m.strength, reasons=list(m.reasons or []),
            entry=dict(m.entry or {}), status=m.status, active=m.active, first_seen_at=m.first_seen_at,
            last_seen_at=m.last_seen_at, reviewed_at=m.reviewed_at, reviewed_by_email=m.reviewed_by_email,
            review_note=m.review_note,
        )


class ScreeningOut(Camel):
    target_id: uuid.UUID
    # not_screened (aún no se revisa), clear, possible (pendientes) o confirmed.
    status: Literal["not_screened", "clear", "possible", "confirmed"]
    screened_at: datetime | None
    pending: int
    confirmed: int
    matches: list[MatchOut]
    lists: int
    disclaimer: str = DISCLAIMER


class ReviewInput(Camel):
    decision: Literal["confirmed", "dismissed", "pending"]
    note: str = Field(default="", max_length=2000)


class WatchlistOut(Camel):
    slug: str
    name: str
    publisher: str | None = None
    category: str
    category_label: str
    custom: bool
    enabled: bool
    configured: bool = True
    info_url: str | None = None
    license: str | None = None
    entry_count: int = 0
    last_checked_at: datetime | None = None
    last_changed_at: datetime | None = None
    last_error: str | None = None
    uploaded_by: str | None = None


class CustomListInput(Camel):
    name: str = Field(min_length=2, max_length=200)
    category: Literal["pep", "sanctions", "tax", "debarment", "other"] = "pep"
    # Contenido del archivo CSV tal cual (el tablero lo lee en el navegador).
    csv: str = Field(min_length=1, max_length=50_000_000)


class CustomListResult(Camel):
    slug: str
    entries: int
    added: int
    changed: int
    removed: int
