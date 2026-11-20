"""Coincidencia de nombres contra listas negras (sanciones, SAT, inhabilitados).

Una coincidencia nunca prueba que sea la misma persona: solo propone candidatos para que un analista los confirme o
los descarte. Por eso se compara con tolerancia (acentos, orden, faltas de ortografía, segundo apellido ausente) y
luego se afina con los datos que haya: RFC/CURP/pasaporte, fecha de nacimiento y nacionalidad.
"""
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from rapidfuzz import fuzz
from rapidfuzz.distance import OSA

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

# Nombres comunes. Cada palabra aporta log2(registros / registros que la llevan) bits de información: en la lista PEP
# nacional "maria" o "hernandez" aportan 4 bits y "sheinbaum" 16. Si un nombre solo coincide en parte (sobran palabras
# en uno de los dos), lo que sí coincide debe distinguir a una persona entre todas las de las listas; si no, por cada bit
# que falte se restan COMMON_PENALTY puntos. COMMON_SLACK son los bits que se perdonan. Con la lista nacional, "Juan
# Pérez" contra "Juan Carlos Pérez Gómez" pierde 32 puntos (habría unos 700 así) y "Claudia Sheinbaum" contra "Claudia
# Sheinbaum Pardo" no pierde nada.
COMMON_SLACK = 0.0
COMMON_PENALTY = 5.0


# slots: una lista PEP puede traer cientos de miles de registros y el revisor los tiene todos en memoria.
@dataclass(frozen=True, slots=True)
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


# Hipocorísticos y abreviaturas de nombres de pila comunes en México y Latinoamérica: "Pepe" es José, "Ma." es María,
# "Lupita" es Guadalupe. Cada uno apunta a su nombre completo (ya en minúsculas y sin acentos).
NICKNAMES = {
    "pepe": "jose", "chepe": "jose", "jos": "jose", "paco": "francisco", "pancho": "francisco", "fco": "francisco",
    "frank": "francisco", "kiko": "francisco", "lupe": "guadalupe", "lupita": "guadalupe", "gpe": "guadalupe",
    "ma": "maria", "mari": "maria", "chuy": "jesus", "chucho": "jesus", "memo": "guillermo",
    "tono": "antonio", "tony": "antonio", "nacho": "ignacio", "chava": "salvador", "chavo": "salvador",
    "lalo": "eduardo", "quique": "enrique", "kike": "enrique", "rafa": "rafael", "fer": "fernando", "fdo": "fernando",
    "alex": "alejandro", "beto": "alberto", "rober": "roberto", "bob": "roberto",
    "charly": "carlos", "carlitos": "carlos", "juanito": "juan", "juancho": "juan", "nando": "fernando",
    "poncho": "alfonso", "goyo": "gregorio", "licha": "alicia", "chela": "graciela", "chelo": "consuelo",
    "concha": "concepcion", "conchita": "concepcion", "conchi": "concepcion", "lola": "dolores", "lolita": "dolores",
    "pili": "pilar", "paty": "patricia", "pati": "patricia", "naty": "natalia", "susy": "susana",
    "betty": "beatriz", "bety": "beatriz", "rosy": "rosa", "chayo": "rosario",
    "meche": "mercedes", "mague": "margarita", "maggie": "margarita", "tere": "teresa", "teresita": "teresa",
    "vicky": "victoria", "gaby": "gabriela", "pepa": "josefa", "pina": "josefina", "fina": "josefina",
    "nico": "nicolas", "santi": "santiago", "migue": "miguel", "dani": "daniel", "edu": "eduardo", "mike": "miguel",
    "jorch": "jorge", "chema": "jose", "lencho": "lorenzo", "chencho": "crescencio", "cuco": "refugio",
    "cuca": "refugio", "willy": "guillermo", "billy": "guillermo",
}


def canonical(token: str) -> str:
    return NICKNAMES.get(token, token)


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
    # Día o mes en 00 ("00/00/1964"): solo se sabe el año.
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:T.*)?", v):
        return f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}" if int(m[2]) and int(m[3]) else m[1]
    if m := re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", v):
        return f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}" if int(m[2]) and int(m[1]) else m[3]
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


def _gender_pair(a: str, b: str) -> bool:
    """Juan/Juana, Mario/María, Gabriel/Gabriela: nombres que solo cambian por el género son personas distintas."""
    if len(a) > len(b):
        a, b = b, a
    if b == a + "a":
        return True
    return len(a) == len(b) and a[:-1] == b[:-1] and {a[-1], b[-1]} == {"a", "o"}


def _token_sim(a: str, b: str) -> float:
    """0 a 1. Se toleran errores que suenan igual y una o dos letras de diferencia en palabras largas, no más:
    "Julián" no es "Juan" ni "Martínez" es "Martín", aunque se parezcan letra por letra."""
    if a == b:
        return 1.0
    # Iniciales: "J." contra "Juan".
    if len(a) == 1 or len(b) == 1:
        return 0.85 if a[0] == b[0] else 0.0
    if canonical(a) == canonical(b):
        return 0.9  # "Pepe" y "José", "Ma." y "María"
    if _gender_pair(a, b):
        return 0.0
    if phonetic(a) == phonetic(b):
        return 0.95
    shortest = min(len(a), len(b))
    distance = OSA.distance(a, b, score_cutoff=2)  # con trasposiciones: "Lopze" es "Lopez"
    if distance == 1 and shortest >= 4:
        return 0.9
    if distance == 2 and shortest >= 8:
        return 0.85
    return 0.0


TokenInfo = Callable[[str], float]


def name_score(a: str, b: str, organization: bool = False, info: TokenInfo | None = None,
               total_info: float = 0.0) -> float:
    """0 a 100. Cada palabra del nombre más corto busca su pareja en el otro; las palabras sobrantes restan poco
    (las listas suelen omitir el segundo apellido) pero un nombre de una sola palabra no basta para una persona.

    Con `info` (bits de información de cada palabra, ver COMMON_SLACK) y `total_info` (bits necesarios para distinguir
    a un registro entre todos), una coincidencia parcial de palabras muy comunes ("Juan Pérez" contra "Juan Carlos
    Pérez Gómez") pierde puntos: en una lista de 660 mil personas habría cientos de candidatos así."""
    return _name_match(a, b, organization, info, total_info)[0]


def _name_match(a: str, b: str, organization: bool, info: TokenInfo | None,
                total_info: float) -> tuple[float, float]:
    """(calificación, puntos restados por nombre común)."""
    ta, tb = name_tokens(a, organization), name_tokens(b, organization)
    if not ta or not tb:
        return 0.0, 0.0
    if "".join(ta) == "".join(tb):
        return 100.0, 0.0
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(short) == 1 and len(long_) > 1 and not organization:
        return 0.0, 0.0
    remaining = list(long_)
    total = bits = 0.0
    for token in short:
        best, best_i = 0.0, -1
        for i, other in enumerate(remaining):
            s = _token_sim(token, other)
            if s > best:
                best, best_i = s, i
        if best == 0.0:
            return 0.0, 0.0  # una palabra sin pareja: "Juan Pérez" no es "Juan Gómez"
        total += best
        if info is not None:
            # Una inicial distingue poco; una palabra con error vale lo que la más común de las dos.
            bits += 1.0 if min(len(token), len(remaining[best_i])) == 1 else min(info(token), info(remaining[best_i]))
        remaining.pop(best_i)
    score = 100 * total / len(short) - 6 * len(remaining)
    common = 0.0
    if info is not None and remaining and not organization:
        common = COMMON_PENALTY * max(0.0, total_info - COMMON_SLACK - bits)
        score -= common
    if organization:
        # En empresas importa más el nombre completo; se mezcla con la comparación de cadenas.
        score = min(score, fuzz.token_sort_ratio(" ".join(ta), " ".join(tb)) + 5)
    return max(score, 0.0), common


def compare(subject: Subject, record: WatchlistRecord, info: TokenInfo | None = None,
            total_info: float = 0.0) -> MatchResult | None:
    """Compara el objetivo con un registro. None si no llega a SHOW_MIN. `info` y `total_info` vienen del índice y
    sirven para castigar las coincidencias parciales de nombres muy comunes (ver name_score)."""
    if not compatible(subject.kind, record.kind):
        return None
    organization = subject.kind != TargetKind.PERSON
    best, best_pair, common = 0.0, ("", ""), 0.0
    for listed in record.names():
        if not is_latin(listed):
            continue
        for own in subject.names:
            s, c = _name_match(own, listed, organization, info, total_info)
            if s > best:
                best, best_pair, common = s, (own, listed), c

    reasons: list[str] = []
    ids_own = {clean_identifier(i) for i in subject.identifiers if clean_identifier(i)}
    ids_listed = {clean_identifier(i) for i in record.identifiers if clean_identifier(i)}
    same_id = ids_own & ids_listed
    if same_id:
        reasons.append(f"Identificador igual ({next(iter(same_id))})")
        return MatchResult(record, 100.0, Strength.STRONG, best_pair[0] or subject.names[0],
                           best_pair[1] or record.name, reasons)
    own_date = normalize_date(subject.birth_date)
    listed_dates = {d for d in (normalize_date(x) for x in record.birth_dates) if d}
    # La misma fecha de nacimiento completa distingue a una persona mejor que cualquier apellido: anula lo restado por
    # nombre común.
    if common and own_date and len(own_date) == 10 and own_date in listed_dates:
        best, common = min(best + common, 100.0), 0.0
    if best < SHOW_MIN - 10:
        return None

    reasons.append(f"Nombre {best:.0f}% parecido: «{best_pair[0]}» y «{best_pair[1]}»")
    if common >= 1:
        reasons.append(f"Coincide solo en parte un nombre común (−{common:.0f})")
    score = best
    extra_match = False
    # RFC: si los dos lo tienen y es distinto, casi seguro es otro contribuyente.
    rfc_own = {i for i in ids_own if _looks_like_rfc(i)}
    rfc_listed = {i for i in ids_listed if _looks_like_rfc(i)}
    if rfc_own and rfc_listed:
        score -= 30
        reasons.append("RFC distinto")

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
    registros que comparten palabras (por su clave fonética o su prefijo; dos si el objetivo es una persona) o un
    identificador. También sabe cuánto distingue cada palabra según cuántos registros la llevan."""

    def __init__(self, records: Iterable[WatchlistRecord]) -> None:
        self.records: list[WatchlistRecord] = list(records)
        self._by_key: dict[str, list[int]] = {}
        self._by_id: dict[str, list[int]] = {}
        frequency: Counter[str] = Counter()
        for i, r in enumerate(self.records):
            words: set[str] = set()
            organization = r.kind != EntryKind.PERSON
            for n in r.names():
                if is_latin(n):
                    words.update(name_tokens(n, organization))
            keys = _keys(words)
            frequency.update(words)
            for k in keys:
                self._by_key.setdefault(k, []).append(i)
            for ident in {clean_identifier(x) for x in r.identifiers}:
                if ident:
                    self._by_id.setdefault(ident, []).append(i)
        # Bits de información de cada palabra (ver COMMON_SLACK). Una palabra que no está en ninguna lista vale como
        # la más rara.
        n = max(len(self.records), 1)
        self.total_info = math.log2(n)
        self._info = {w: math.log2(n / c) for w, c in frequency.items()}

    def token_info(self, token: str) -> float:
        return self._info.get(token, self.total_info)

    def __len__(self) -> int:
        return len(self.records)

    def screen(self, subject: Subject) -> list[MatchResult]:
        if subject.kind == TargetKind.COUNTRY:
            return []
        organization = subject.kind != TargetKind.PERSON
        candidates: set[int] = set()
        for n in subject.names:
            tokens = [t for t in dict.fromkeys(name_tokens(n, organization)) if len(t) > 1]
            # Una persona necesita al menos dos palabras en común (ver name_score): se cuentan cuántas palabras del
            # nombre tiene cada registro y no se compara contra los miles que solo comparten "María" o "García".
            hits: Counter[int] = Counter()
            for t in tokens:
                found: set[int] = set()
                for k in _keys([t]):
                    found.update(self._by_key.get(k, ()))
                hits.update(found)
            need = 1 if organization or len(tokens) < 2 else 2
            candidates.update(i for i, c in hits.items() if c >= need)
        for ident in subject.identifiers:
            candidates.update(self._by_id.get(clean_identifier(ident), ()))
        results = [m for i in candidates
                   if (m := compare(subject, self.records[i], self.token_info, self.total_info)) is not None]
        return sorted(results, key=lambda m: m.score, reverse=True)


def _keys(tokens: Iterable[str]) -> set[str]:
    # Clave fonética (errores de ortografía que suenan igual), las 3 primeras letras (errores al final) y la del nombre
    # completo de un hipocorístico ("Pepe" encuentra a José).
    keys = set()
    for t in tokens:
        if len(t) > 1:
            keys.add("p:" + phonetic(t))
            keys.add("s:" + t[:3])
            if (full := canonical(t)) != t:
                keys.add("p:" + phonetic(full))
    return keys
