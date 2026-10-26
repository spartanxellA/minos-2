"""Objetivos de monitoreo y la regla que decide si un texto realmente habla de ellos."""
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from enum import StrEnum


class TargetKind(StrEnum):
    PERSON = "Person"
    COMPANY = "Company"
    INSTITUTION = "Institution"
    GOVERNMENT_AREA = "GovernmentArea"
    COUNTRY = "Country"


@dataclass
class MonitoredTarget:
    """Persona, empresa, institución, área de gobierno o país cuyo riesgo reputacional se monitorea."""

    name: str
    kind: TargetKind = TargetKind.PERSON
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    # Otras formas de nombrarlo: siglas, apodos, nombre corto.
    aliases: list[str] = field(default_factory=list)
    # Términos adicionales que deben acompañar a la búsqueda (cargo, empresa, ciudad).
    keywords: list[str] = field(default_factory=list)
    # Términos que descartan una mención (homónimos, otros contextos).
    excluded_terms: list[str] = field(default_factory=list)
    # Cuentas oficiales por fuente, por ejemplo "x" → "@cuenta".
    handles: dict[str, str] = field(default_factory=dict)
    enabled: bool = True

    def search_names(self) -> list[str]:
        seen: set[str] = set()
        names = []
        for n in [self.name, *self.aliases]:
            if n and n.strip() and n.lower() not in seen:
                seen.add(n.lower())
                names.append(n)
        return names


_NON_WORD = re.compile(r"[^\w@#]+")


def normalize(value: str) -> str:
    """Minúsculas, sin acentos, solo letras, dígitos, @ y #, con un espacio a cada lado para buscar términos completos."""
    decomposed = unicodedata.normalize("NFD", value.lower())
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return " " + " ".join(_NON_WORD.sub(" ", stripped.replace("_", " ")).split()) + " "


def _contains_term(haystack: str, term: str) -> bool:
    term = normalize(term).strip()
    return bool(term) and f" {term} " in haystack


def is_relevant(target: MonitoredTarget, text: str) -> bool:
    """Debe contener el nombre, un alias o una cuenta oficial, y ninguno de los términos excluidos."""
    if not text or not text.strip():
        return False
    return is_relevant_normalized(target, normalize(text))


def is_relevant_normalized(target: MonitoredTarget, haystack: str) -> bool:
    """is_relevant con el texto ya pasado por normalize(), para revisar un texto contra muchos objetivos."""
    if any(_contains_term(haystack, t) for t in target.excluded_terms):
        return False
    return any(_contains_term(haystack, n) for n in target.search_names()) or any(
        _contains_term(haystack, h) for h in target.handles.values()
    )
