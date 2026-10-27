"""Coincidencia de nombres contra listas negras (sanciones, SAT, inhabilitados).

Una coincidencia nunca prueba que sea la misma persona: solo propone candidatos para que un analista los confirme o
los descarte. Por eso se compara con tolerancia (acentos, orden, faltas de ortografía, segundo apellido ausente) y
luego se afina con los datos que haya: RFC/CURP/pasaporte, fecha de nacimiento y nacionalidad.
"""
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler

from .targets import TargetKind


class EntryKind(StrEnum):
    PERSON = "person"
    ORGANIZATION = "organization"
    VESSEL = "vessel"
    OTHER = "other"


class Strength(StrEnum):
    POSSIBLE = "possible"
    STRONG = "strong"


# Por debajo no se muestra; con 95 o más y un dato extra igual (o un identificador igual) es "fuerte".
SHOW_MIN = 80
STRONG_MIN = 95


@dataclass(frozen=True)
class WatchlistRecord:
    """Un registro de una lista, ya normalizado por su lector."""

    source: str
    external_id: str
    kind: EntryKind
    name: str
    aliases: Sequence[str] = ()
    birth_dates: Sequence[str] = ()
    nationalities: Sequence[str] = ()
    # RFC, CURP, pasaporte, número de registro… tal como vienen; se comparan sin espacios ni guiones.
    identifiers: Sequence[str] = ()
    programs: Sequence[str] = ()
    listed_on: str | None = None
    # Situación en la lista cuando importa (SAT: "Presunto", "Definitivo").
    status: str | None = None
    url: str | None = None
    notes: str | None = None

    def names(self) -> list[str]:
        return _unique([self.name, *self.aliases])


@dataclass(frozen=True)
class Subject:
    """Lo que se sabe del objetivo para compararlo."""

    kind: TargetKind
    names: Sequence[str]
    birth_date: str | None = None
    nationality: str | None = None
    identifiers: Sequence[str] = ()


@dataclass(frozen=True)
class MatchResult:
    record: WatchlistRecord
    score: float
    strength: Strength
    matched_name: str
    listed_name: str
    reasons: list[str] = field(default_factory=list)


# --- Normalización --------------------------------------------------------------------------------

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
# Formas jurídicas y títulos: no distinguen a nadie y sí generan falsos parecidos.
LEGAL_FORMS = {
    "sa", "cv", "de", "s", "rl", "sapi", "sab", "sc", "ac", "spr", "sas", "llc", "ltd", "limited", "inc", "corp",
    "corporation", "co", "company", "gmbh", "ag", "srl", "plc", "jsc", "pjsc", "ojsc", "ooo", "llp", "lp", "bv", "nv",
    "spa", "cia", "compania", "sociedad", "anonima", "variable", "capital", "responsabilidad", "limitada",
}
TITLES = {"lic", "licenciado", "licenciada", "ing", "dr", "dra", "sr", "sra", "srta", "mr", "mrs", "ms", "don", "dona",
          "gen", "general", "col", "coronel", "mtro", "mtra", "c", "prof", "sheikh", "haji", "mullah"}
# Partículas de apellidos y artículos: "de la", "van", "bin"… no deben contar como coincidencia por sí solas.
PARTICLES = {"de", "del", "la", "las", "los", "y", "e", "van", "von", "der", "da", "das", "do", "dos", "di", "le",
             "bin", "ibn", "bint", "al", "el", "abu", "the", "of", "and"}


def ascii_fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c)).replace("ß", "ss").replace("ø", "o")


def name_tokens(value: str, organization: bool = False) -> list[str]:
    """Palabras útiles de un nombre: minúsculas, sin acentos, sin títulos, partículas ni formas jurídicas."""
    raw = _NON_ALNUM.sub(" ", ascii_fold(value)).split()
    if organization:
        # "S.A. de C.V." llega como s a de c v: se juntan las letras sueltas seguidas (sa, cv).
        joined: list[str] = []
        in_run = False
        for t in raw:
            if len(t) == 1 and in_run:
                joined[-1] += t
            else:
                joined.append(t)
                in_run = len(t) == 1
        raw = joined
    drop = PARTICLES | TITLES | (LEGAL_FORMS if organization else set())
    tokens = [t for t in raw if t not in drop]
    return tokens or raw


def is_latin(value: str) -> bool:
    """Los alias en alfabetos no latinos (árabe, cirílico…) no se comparan: la transliteración daría basura."""
    letters = [c for c in value if c.isalpha()]
    return bool(letters) and sum(1 for c in ascii_fold("".join(letters)) if "a" <= c <= "z") / len(letters) > 0.6


def phonetic(token: str) -> str:
    """Clave fonética sencilla pensada para el español: Gonzalez = Gonsales, Vazquez = Basques, Yañez = Llanes."""
    t = token
    for a, b in (("ph", "f"), ("sch", "s"), ("ch", "x"), ("sh", "x"), ("qu", "k"), ("gue", "ge"), ("gui", "gi"),
                 ("ll", "y"), ("ce", "se"), ("ci", "si"), ("z", "s"), ("c", "k"), ("q", "k"), ("v", "b"), ("w", "u"),
                 ("ge", "je"), ("gi", "ji"), ("x", "j"), ("ks", "j"), ("i", "y"), ("h", "")):
        t = t.replace(a, b)
    t = re.sub(r"(.)\1+", r"\1", t)
    return t or token


def clean_identifier(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", ascii_fold(value).upper())


def normalize_date(value: str | None) -> str | None:
    """'1970-05-03', '03/05/1970', '1970' o '03 May 1970' → '1970-05-03' o '1970'. Lo demás se ignora."""
    if not value:
        return None
    v = value.strip()
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:T.*)?", v):
        return f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}"
    if m := re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", v):
        return f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}"
    if m := re.fullmatch(r"(\d{1,2}) ([A-Za-z]{3})[a-z]* (\d{4})", v):
        month = MONTHS.get(m[2].lower())
        return f"{m[3]}-{month:02d}-{int(m[1]):02d}" if month else m[3]
    if m := re.search(r"\b(1[89]\d{2}|20\d{2})\b", v):
        return m[1]
    return None


MONTHS = {k: i + 1 for i, k in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

# Nombres y códigos de los países que más aparecen, para comparar "México" con "Mexico" o "MX".
COUNTRY_ALIASES = {
    "mx": ["mexico", "mexicana", "mexicano", "mex"], "us": ["united states", "estados unidos", "usa", "eua", "eeuu"],
    "co": ["colombia"], "ve": ["venezuela"], "gt": ["guatemala"], "hn": ["honduras"], "sv": ["el salvador", "salvador"],
    "ni": ["nicaragua"], "cr": ["costa rica"], "pa": ["panama"], "cu": ["cuba"], "do": ["dominican republic",
    "republica dominicana"], "ec": ["ecuador"], "pe": ["peru"], "bo": ["bolivia"], "cl": ["chile"], "ar": ["argentina"],
    "uy": ["uruguay"], "py": ["paraguay"], "br": ["brazil", "brasil"], "es": ["spain", "espana"], "ca": ["canada"],
    "gb": ["united kingdom", "reino unido", "uk"], "fr": ["france", "francia"], "de": ["germany", "alemania"],
    "it": ["italy", "italia"], "ru": ["russia", "russian federation", "rusia"], "cn": ["china"], "ir": ["iran"],
    "kp": ["north korea", "korea north", "corea del norte"], "sy": ["syria", "siria"], "af": ["afghanistan",
    "afganistan"], "iq": ["iraq", "irak"], "lb": ["lebanon", "libano"], "ly": ["libya", "libia"], "ye": ["yemen"],
    "so": ["somalia"], "sd": ["sudan"], "pk": ["pakistan"], "tr": ["turkey", "turkiye", "turquia"],
    "ua": ["ukraine", "ucrania"], "by": ["belarus", "bielorrusia"], "il": ["israel"], "in": ["india"],
}
_COUNTRY = {alias: code for code, names in COUNTRY_ALIASES.items() for alias in [code, *names]}


def country_code(value: str | None) -> str | None:
    if not value:
        return None
    v = " ".join(_NON_ALNUM.sub(" ", ascii_fold(value)).split())
    return _COUNTRY.get(v) or _COUNTRY.get(v.removeprefix("republic of ").removesuffix(" republic of"))


def _unique(values: Iterable[str | None]) -> list[str]:
    seen, out = set(), []
    for v in values:
        if v and v.strip() and v.strip().lower() not in seen:
            seen.add(v.strip().lower())
            out.append(v.strip())
    return out


# --- Comparación ----------------------------------------------------------------------------------


def compatible(subject: TargetKind, entry: EntryKind) -> bool:
    if subject == TargetKind.COUNTRY or entry == EntryKind.VESSEL:
        return False
    if entry == EntryKind.OTHER:
        return True
    return (entry == EntryKind.PERSON) == (subject == TargetKind.PERSON)


def _token_sim(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if phonetic(a) == phonetic(b):
        return 0.95
    # Iniciales: "J." contra "Juan".
    if len(a) == 1 or len(b) == 1:
        return 0.85 if a[0] == b[0] else 0.0
    return JaroWinkler.similarity(a, b) if min(len(a), len(b)) >= 4 else fuzz.ratio(a, b) / 100


def name_score(a: str, b: str, organization: bool = False) -> float:
    """0 a 100. Cada palabra del nombre más corto busca su pareja en el otro; las palabras sobrantes restan poco
    (las listas suelen omitir el segundo apellido) pero un nombre de una sola palabra no basta para una persona."""
    ta, tb = name_tokens(a, organization), name_tokens(b, organization)
    if not ta or not tb:
        return 0.0
    if "".join(ta) == "".join(tb):
        return 100.0
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(short) == 1 and len(long_) > 1 and not organization:
        return 0.0
    remaining = list(long_)
    total = 0.0
    for token in short:
        best, best_i = 0.0, -1
        for i, other in enumerate(remaining):
            s = _token_sim(token, other)
            if s > best:
                best, best_i = s, i
        if best < 0.75:
            return 0.0  # una palabra sin pareja: "Juan Pérez" no es "Juan Gómez"
        total += best
        remaining.pop(best_i)
    score = 100 * total / len(short) - 6 * len(remaining)
    if organization:
        # En empresas importa más el nombre completo; se mezcla con la comparación de cadenas.
        score = min(score, fuzz.token_sort_ratio(" ".join(ta), " ".join(tb)) + 5)
    return max(score, 0.0)


def compare(subject: Subject, record: WatchlistRecord) -> MatchResult | None:
    """Compara el objetivo con un registro. None si no llega a SHOW_MIN."""
    if not compatible(subject.kind, record.kind):
        return None
    organization = subject.kind != TargetKind.PERSON
    best, best_pair = 0.0, ("", "")
    for listed in record.names():
        if not is_latin(listed):
            continue
        for own in subject.names:
            s = name_score(own, listed, organization)
            if s > best:
                best, best_pair = s, (own, listed)

    reasons: list[str] = []
    ids_own = {clean_identifier(i) for i in subject.identifiers if clean_identifier(i)}
    ids_listed = {clean_identifier(i) for i in record.identifiers if clean_identifier(i)}
    same_id = ids_own & ids_listed
    if same_id:
        reasons.append(f"Identificador igual ({next(iter(same_id))})")
        return MatchResult(record, 100.0, Strength.STRONG, best_pair[0] or subject.names[0],
                           best_pair[1] or record.name, reasons)
    if best < SHOW_MIN - 10:
        return None

    reasons.append(f"Nombre {best:.0f}% parecido: «{best_pair[0]}» y «{best_pair[1]}»")
    score = best
    extra_match = False
    # RFC: si los dos lo tienen y es distinto, casi seguro es otro contribuyente.
    rfc_own = {i for i in ids_own if _looks_like_rfc(i)}
    rfc_listed = {i for i in ids_listed if _looks_like_rfc(i)}
    if rfc_own and rfc_listed:
        score -= 30
        reasons.append("RFC distinto")

    own_date = normalize_date(subject.birth_date)
    listed_dates = {d for d in (normalize_date(x) for x in record.birth_dates) if d}
    if own_date and listed_dates:
        if own_date in listed_dates or (len(own_date) == 4 and any(d.startswith(own_date) for d in listed_dates)):
            score += 5
            extra_match = True
            reasons.append(f"Fecha de nacimiento igual ({own_date})")
        elif any(d[:4] == own_date[:4] for d in listed_dates):
            score += 2
            extra_match = len(own_date) == 4
            reasons.append(f"Mismo año de nacimiento ({own_date[:4]})")
        else:
            score -= 25
            reasons.append("Fecha de nacimiento distinta (" + ", ".join(sorted(listed_dates)) + ")")

    own_country = country_code(subject.nationality)
    listed_countries = {c for c in (country_code(x) for x in record.nationalities) if c}
    if own_country and listed_countries:
        if own_country in listed_countries:
            score += 3
            extra_match = True
            reasons.append("Misma nacionalidad")
        else:
            score -= 10
            reasons.append("Nacionalidad distinta")

    score = round(min(max(score, 0), 100), 1)
    if score < SHOW_MIN:
        return None
    strength = Strength.STRONG if score >= STRONG_MIN and extra_match else Strength.POSSIBLE
    return MatchResult(record, score, strength, best_pair[0], best_pair[1], reasons)


def _looks_like_rfc(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z&]{3,4}\d{6}[A-Z0-9]{3}", value))


class ScreeningIndex:
    """Índice en memoria de todos los registros. Para no comparar contra decenas de miles, primero se buscan los
    registros que comparten al menos una palabra (por su clave fonética o su prefijo) o un identificador."""

    def __init__(self, records: Iterable[WatchlistRecord]) -> None:
        self.records: list[WatchlistRecord] = list(records)
        self._by_key: dict[str, list[int]] = {}
        self._by_id: dict[str, list[int]] = {}
        for i, r in enumerate(self.records):
            keys: set[str] = set()
            organization = r.kind != EntryKind.PERSON
            for n in r.names():
                if is_latin(n):
                    keys.update(_keys(name_tokens(n, organization)))
            for k in keys:
                self._by_key.setdefault(k, []).append(i)
            for ident in {clean_identifier(x) for x in r.identifiers}:
                if ident:
                    self._by_id.setdefault(ident, []).append(i)

    def __len__(self) -> int:
        return len(self.records)

    def screen(self, subject: Subject) -> list[MatchResult]:
        if subject.kind == TargetKind.COUNTRY:
            return []
        organization = subject.kind != TargetKind.PERSON
        candidates: set[int] = set()
        for n in subject.names:
            for k in _keys(name_tokens(n, organization)):
                candidates.update(self._by_key.get(k, ()))
        for ident in subject.identifiers:
            candidates.update(self._by_id.get(clean_identifier(ident), ()))
        results = [m for i in candidates if (m := compare(subject, self.records[i])) is not None]
        return sorted(results, key=lambda m: m.score, reverse=True)


def _keys(tokens: Iterable[str]) -> set[str]:
    # Clave fonética (errores de ortografía que suenan igual) y las 3 primeras letras (errores al final).
    keys = set()
    for t in tokens:
        if len(t) > 1:
            keys.add("p:" + phonetic(t))
            keys.add("s:" + t[:3])
    return keys
