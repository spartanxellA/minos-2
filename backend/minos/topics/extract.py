"""Temas de un conjunto de menciones: palabras, frases de dos palabras y hashtags, sin palabras vacías ni el nombre del
propio objetivo (sale en casi todas y taparía todo lo demás).

Se cuenta en cuántas menciones aparece cada término, no cuántas veces: una publicación que repite «fraude» diez veces
pesa lo mismo que otra que lo dice una vez.
"""
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from .stopwords import STOPWORDS, fold

TermKind = Literal["word", "phrase", "hashtag"]

_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_HANDLE = re.compile(r"(?<!\w)@\w+")
_HASHTAG = re.compile(r"(?<!\w)#(\w*[^\W\d_]\w*)")
# Corta en signos de puntuación: una frase no cruza de una oración a otra.
_CLAUSE = re.compile(r"[.,;:!?¡¿()\[\]{}\"“”«»|/\\\n…–—-]+")
_WORD = re.compile(r"[^\W_]+")
_LETTER = re.compile(r"[^\W\d_]")

MIN_LENGTH = 3
# Una frase puede saltar una de estas: «crisis del agua», «Estado de México», «price of oil», «prix du pétrole».
_LINKS = frozenset({"de", "del", "of", "du", "des"})


@dataclass
class Term:
    term: str
    kind: TermKind
    count: int
    positive: int
    negative: int


@dataclass
class _Tally:
    count: int = 0
    positive: int = 0
    negative: int = 0


def _keep(word: str, exclude: set[str]) -> bool:
    if len(word) < MIN_LENGTH or not _LETTER.search(word):
        return False
    folded = fold(word)
    return folded not in STOPWORDS and folded not in exclude


def _spelling(seen: Counter) -> str:
    """La forma más común, salvo que gane solo por iniciar oraciones: «inversión extranjera» y no «Inversión
    extranjera» si también se escribe seguido en minúscula, pero «Pemex» aunque alguien escriba «pemex»."""
    top, n = seen.most_common(1)[0]
    lower = top[:1].lower() + top[1:]
    return lower if lower != top and seen[lower] * 2 > n else top


def name_words(names: Iterable[str]) -> set[str]:
    """Palabras del nombre, alias y cuentas del objetivo, ya normalizadas."""
    out: set[str] = set()
    for name in names:
        out.update(fold(w) for w in _WORD.findall(name or "") if _LETTER.search(w))
    return out


def extract_topics(
    mentions: Iterable[tuple[str, str]], exclude: set[str] = frozenset(), limit: int = 80,
) -> tuple[int, list[Term]]:
    """mentions: (texto, sentimiento: "positive", "Negative"…). Regresa cuántas menciones se leyeron y los términos, del más mencionado al menos."""
    tallies: dict[tuple[str, str], _Tally] = defaultdict(_Tally)
    # Cómo se escribe cada término, para mostrar la forma más común («Pemex», no «pemex»).
    spellings: dict[tuple[str, str], Counter] = defaultdict(Counter)
    total = 0

    for text, sentiment in mentions:
        total += 1
        seen: set[tuple[str, str]] = set()
        text = _HANDLE.sub(" ", _URL.sub(" ", text or ""))

        for tag in _HASHTAG.findall(text):
            key = ("hashtag", fold(tag))
            if key[1] in exclude or key[1] in STOPWORDS:
                continue
            seen.add(key)
            spellings[key]["#" + tag] += 1
        text = _HASHTAG.sub(" ", text)

        for clause in _CLAUSE.split(text):
            words = _WORD.findall(clause)
            keep = [_keep(w, exclude) for w in words]
            # Un número corto vale dentro de una frase («Línea 12», «COVID 19») pero no solo.
            joins = [k or (w.isdigit() and len(w) <= 4) for w, k in zip(words, keep)]
            for i, w in enumerate(words):
                if keep[i]:
                    key = ("word", fold(w))
                    seen.add(key)
                    spellings[key][w] += 1
                if i + 1 < len(words) and joins[i] and joins[i + 1] and (keep[i] or keep[i + 1]):
                    phrase = f"{w} {words[i + 1]}"
                    key = ("phrase", fold(phrase))
                    seen.add(key)
                    spellings[key][phrase] += 1
                if i + 2 < len(words) and keep[i] and keep[i + 2] and fold(words[i + 1]) in _LINKS:
                    phrase = f"{w} {words[i + 1]} {words[i + 2]}"
                    key = ("phrase", fold(phrase))
                    seen.add(key)
                    spellings[key][phrase] += 1

        sentiment = (sentiment or "").lower()
        for key in seen:
            tally = tallies[key]
            tally.count += 1
            tally.positive += sentiment == "positive"
            tally.negative += sentiment == "negative"

    # Con pocas menciones cualquier palabra suelta cuenta; con más, lo que sale una sola vez es ruido.
    min_count = 1 if total < 20 else 2
    phrases = sorted(
        ((k, t) for k, t in tallies.items() if k[0] == "phrase" and t.count >= max(2, min_count)),
        key=lambda kt: -kt[1].count,
    )
    # Una palabra que casi siempre va dentro de frases sobra: «crisis del agua» ya dice «agua», y «Nuevo León» con
    # «nuevo hospital» ya dicen «nuevo».
    inside: dict[str, int] = defaultdict(int)
    for (_, phrase), tally in phrases:
        for word in set(phrase.split()):
            inside[word] += tally.count
    covered = {w for w, n in inside.items() if tallies[("word", w)].count - n <= tallies[("word", w)].count * 0.25}

    candidates = [
        (k, t) for k, t in tallies.items()
        if t.count >= min_count and (k[0] != "phrase" or t.count >= 2) and not (k[0] == "word" and k[1] in covered)
    ]
    candidates.sort(key=lambda kt: (-kt[1].count, kt[0][0] == "word", kt[0][1]))
    return total, [
        Term(term=_spelling(spellings[k]), kind=k[0], count=t.count, positive=t.positive, negative=t.negative)
        for k, t in candidates[:limit]
    ]
