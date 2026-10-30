"""De texto a lugar con el nomenclátor: un campo de ubicación ("Monterrey, N.L.") o el texto de una mención."""
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from .gazetteer import INDEX, MAX_WORDS, GazetteerEntry, Name, key

# Un nombre ambiguo (Guerrero, Hidalgo, León) solo cuenta en el texto si lo antecede una de estas palabras.
_CONTEXT = {"en", "desde"}
_CONTEXT_PAIRS = {
    ("estado", "de"), ("ciudad", "de"), ("municipio", "de"), ("puerto", "de"), ("capital", "de"),
    ("gobierno", "de"), ("gobernador", "de"), ("gobernadora", "de"), ("alcalde", "de"), ("alcaldesa", "de"),
    ("congreso", "de"), ("habitantes", "de"), ("vecinos", "de"),
}
_RANK = {"country": 0, "region": 1, "city": 2}


@dataclass(frozen=True)
class _Match:
    names: list[Name]
    start: int


def _mask(words: list[str], exclude: Iterable[str]) -> list[str]:
    """Borra del texto los nombres del propio objetivo: si el objetivo es "Nuevo León", nombrarlo no dice de dónde se habla."""
    words = list(words)
    for phrase in exclude:
        k = key(phrase)
        if not k:
            continue
        for i in range(len(words) - len(k) + 1):
            if tuple(words[i:i + len(k)]) == k:
                words[i:i + len(k)] = [""] * len(k)
    return words


def _scan(words: list[str], *, allow_strict: bool, need_context: bool, context_words: set[str] = _CONTEXT) -> list[_Match]:
    out, i, prev_end = [], 0, -1
    while i < len(words):
        for n in range(min(MAX_WORDS, len(words) - i), 0, -1):
            names = INDEX.get(tuple(words[i:i + n]))
            if not names:
                continue
            context = (i > 0 and words[i - 1] in context_words) or (i > 1 and (words[i - 2], words[i - 1]) in _CONTEXT_PAIRS)
            # Una abreviatura ("N.L.", "Son.") vale tras otro lugar ("Monterrey, N.L.") o si es todo el campo ("NL").
            strict_ok = allow_strict and (prev_end == i or (i == 0 and n == len(words)))
            usable = [x for x in names if (strict_ok or not x.strict) and (not need_context or not x.ambiguous or context)]
            if usable:
                out.append(_Match(usable, i))
                i += n
                prev_end = i
                break
        else:
            i += 1
    return out


def _choose(matches: list[_Match], default_country: str) -> list[GazetteerEntry]:
    """Elige entre homónimos (León de Guanajuato o de España) con lo demás que se nombra, o con el país por omisión."""
    countries = {m.names[0].entry.country for m in matches if all(n.entry.precision == "country" for n in m.names)}
    regions = {n.entry.region for m in matches for n in m.names if n.entry.precision == "region"}
    chosen = []
    for m in matches:
        entries = [n.entry for n in m.names]
        for keep in (
            lambda e: e.region is not None and e.region in regions,
            lambda e: e.country in countries,
            lambda e: e.country == default_country,
        ):
            narrowed = [e for e in entries if keep(e)]
            if narrowed:
                entries = narrowed
                break
        chosen.append(entries[0])
    return chosen


def resolve_location(value: str | None, default_country: str = "MX") -> GazetteerEntry | None:
    """Campo de ubicación de un perfil o de una geoetiqueta: gana el lugar más preciso que se nombre."""
    if not value:
        return None
    matches = _scan(list(key(value)), allow_strict=True, need_context=False)
    chosen = _choose(matches, default_country)
    if not chosen:
        return None
    # "Col. Roma, CDMX": lo último suele ser lo más general y lo más claro; manda el país.
    country = chosen[-1].country
    chosen = [e for e in chosen if e.country == country]
    return max(enumerate(chosen), key=lambda p: (_RANK[p[1].precision], -p[0]))[1]


def resolve_text(text: str | None, exclude: Iterable[str] = (), default_country: str = "MX", *, lenient: bool = False) -> GazetteerEntry | None:
    """Lugar que más se menciona en un texto, prefiriendo ciudades y estados sobre países.

    Sin abreviaturas y con los nombres ambiguos solo en contexto. `lenient` acepta además "de" como contexto, para
    nombres de medios ("El Siglo de Torreón", "El Sol de León").
    """
    if not text:
        return None
    words = _mask(list(key(text)), exclude)
    context = _CONTEXT | {"de"} if lenient else _CONTEXT
    chosen = _choose(_scan(words, allow_strict=False, need_context=True, context_words=context), default_country)
    if not chosen:
        return None
    specific = [e for e in chosen if e.precision != "country"] or chosen
    counts = Counter(specific)
    first = {e: i for i, e in reversed(list(enumerate(specific)))}
    return max(counts, key=lambda e: (counts[e], _RANK[e.precision], -first[e]))
