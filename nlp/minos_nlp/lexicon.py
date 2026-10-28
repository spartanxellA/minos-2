"""
Analizador de respaldo en español por diccionario (la API lo reutiliza como respaldo si este servicio no responde).

Cada palabra tiene un peso (+ positivo, - negativo). Una entrada que termina en "*" es una raíz y cubre sus
variantes ("corrupt*" → corrupto, corrupta, corruptos). Reglas de contexto sobre la oración:
- negación ("no", "nunca", "ni", "jamás", "poco"...) en las 3 palabras previas invierte el sentido;
- intensificadores ("muy", "tan", "demasiado"...) lo aumentan y atenuantes ("algo", "medio"...) lo bajan;
- tras "pero", "sin embargo", "aunque"... la segunda parte pesa más (es la que suele dar la opinión);
- frases hechas ("no sirve", "qué vergüenza", "se robó"), emojis y hashtags (#NarcoPresidenta, #FueraX).
"""
import re
import unicodedata

# --- Pesos por palabra (ya sin acentos y en minúsculas) -----------------------------------------------------------
POSITIVE: dict[str, float] = {
    # calidad y desempeño
    "excelente": 2, "bueno": 1, "buena": 1, "buenos": 1, "buenas": 1, "buen": 1, "mejor": 1, "mejores": 1,
    "genial": 1.5, "increible": 1, "impecable": 1.5, "eficaz": 1, "eficiente": 1,
    "eficientes": 1, "capaz": 1, "competente": 1, "acertad*": 1, "brillante": 1.5, "magnific*": 1.5,
    "extraordinari*": 1.5, "maravillos*": 1.5, "estupend*": 1.5, "positiv*": 1, "favorable*": 1, "solid*": 0.5,
    "exitos*": 1.5, "exito": 1.5, "exitos": 1.5, "logro": 1, "logros": 1, "logra": 1, "lograron": 1, "logramos": 1,
    "avance": 1, "avances": 1, "avanza": 0.5, "progreso": 1, "crecimiento": 0.5, "crece": 0.5, "mejora": 1,
    "mejoras": 1, "mejoro": 1, "beneficio": 1, "beneficios": 1, "beneficia": 1, "gano": 1, "gana": 1, "ganamos": 1,
    "triunfo": 1.5, "triunfa": 1.5, "victoria": 1,
    # ética
    "honest*": 1.5, "honrad*": 1.5, "integridad": 1.5, "transparente": 1.5, "transparencia": 1, "etic*": 0.5,
    "confiable": 1, "confianza": 1, "responsable": 0.5, "justo": 1, "justa": 1, "justicia": 0.5, "legitim*": 0.5,
    # afecto y apoyo
    "gracias": 1, "agradec*": 1, "felicidades": 1.5, "felicit*": 1.5, "enhorabuena": 1.5, "apoyo": 1, "apoyamos": 1,
    "apoya": 0.5, "aplauso": 1.5, "aplausos": 1.5, "aplaud*": 1.5, "orgullo": 1.5, "orgullos*": 1.5, "admir*": 1.5,
    "reconocimiento": 1, "reconoce": 0.5, "respeto": 1, "aprecio": 1, "querid*": 1, "amor": 1, "encanta": 1.5,
    "encanto": 1, "fan": 0.5, "bravo": 1.5, "chido": 1, "chida": 1, "padre": 0.3, "chingon": 1.5, "chingona": 1.5,
    "esperanza": 1, "feliz": 1, "alegria": 1, "celebr*": 1, "bienvenid*": 0.5, "lider": 0.5,
    "liderazgo": 1, "visionari*": 1, "inspira*": 1, "ejemplar": 1.5, "digno": 1, "digna": 1, "dignidad": 1,
    "bendicion": 1, "bendiciones": 1, "aprueba": 0.5, "aprobacion": 0.5, "popularidad": 0.5,
}

NEGATIVE: dict[str, float] = {
    # calidad y desempeño
    "malo": 1.5, "mala": 1.5, "malos": 1.5, "malas": 1.5, "mal": 1, "peor": 1.5, "peores": 1.5, "pesim*": 2,
    "horribl*": 2, "terribl*": 2, "fatal": 1.5, "desastr*": 2, "fracas*": 2, "fallid*": 1.5, "falla": 1, "fallas": 1,
    "fallo": 1, "error": 1, "errores": 1, "inutil*": 2, "inept*": 2, "incompetent*": 2, "incapa*": 2,
    "ineficient*": 1.5, "ineficaz": 1.5, "mediocr*": 2, "deficient*": 1.5, "lament*": 1.5, "patetic*": 2,
    "ridicul*": 1.5, "absurd*": 1.5, "caos": 1.5, "caotic*": 1.5, "colaps*": 1.5, "crisis": 1.5, "deterior*": 1.5,
    "retroceso": 1.5, "estancad*": 1, "recesion": 1.5, "deuda": 0.5, "despilfarr*": 2, "derroch*": 2,
    "sobrecosto*": 1.5, "desabasto": 1.5, "escasez": 1.5, "apagon*": 1.5, "inflacion": 0.5, "perdida*": 1,
    "retraso": 1, "retrasos": 1, "atraso": 1, "abandon*": 1.5, "olvidad*": 1,
    "improvis*": 1.5, "irresponsab*": 2, "negligen*": 2, "omis*": 1, "opacidad": 1.5, "opac*": 1,
    "irregularidad*": 1.5, "anomalia*": 1, "simulacion": 1.5, "simula": 1, "populis*": 1, "demagog*": 1.5,
    "autoritari*": 2, "dictador*": 2, "dictadura": 2, "tirano": 2, "tirania": 2, "censura": 1.5, "censur*": 1.5,
    "represion": 2, "reprim*": 2, "militarizacion": 1, "impunidad": 2, "impune*": 2, "injust*": 1.5,
    "ilegal*": 2, "ilegitim*": 2, "inconstitucional": 1.5, "violacion": 1.5, "viola": 1, "violan": 1,
    # crítica pública
    "critica": 1, "criticas": 1, "critican": 1, "criticado*": 1, "cuestiona*": 1, "reprob*": 1.5, "rechaz*": 1,
    "repudi*": 2, "condena*": 1.5, "indign*": 2, "abuche*": 2, "protesta*": 1, "manifestacion*": 0.5,
    "exigen": 1, "reclam*": 1, "queja*": 1, "denuncia*": 1.5, "acusa*": 1.5, "señalan": 0.5, "señalado*": 1,
    "escandal*": 2, "polemic*": 1.5, "controversia*": 1, "renuncia": 1, "renuncie": 1.5, "destitu*": 1.5,
    "investigacion": 1, "investigad*": 1, "investiga": 1, "multa*": 1, "sancion*": 1, "demanda*": 1,
    "vergüenza": 2, "verguenza": 2, "vergonzos*": 2, "desverguenz*": 2, "humill*": 1.5, "decepcion*": 2,
    "decepcionad*": 2, "decepcionante": 2, "traicion*": 2, "traidor*": 2, "engañ*": 2, "engano*": 2,
    "mentir*": 2, "mentira*": 2, "mentiros*": 2, "mintio": 2, "miente": 2, "mienten": 2, "falso": 1.5,
    "falsa": 1.5, "falsos": 1.5, "falsedad*": 1.5, "hipocrit*": 2, "hipocresia": 2, "cinic*": 2, "descarad*": 2,
    "manipul*": 1.5, "propaganda": 1, "arrogan*": 1.5, "soberbi*": 1.5, "prepoten*": 1.5, "abuso": 2, "abusos": 2,
    "abusiv*": 2, "amenaz*": 1.5, "ataque*": 1, "ataca*": 1, "agresion*": 1.5, "agred*": 2, "agresor*": 2,
    "golpe*": 2, "golpea*": 2, "cachetad*": 2, "bofetad*": 2, "patea*": 1.5, "pateo": 1.5, "patada*": 1.5, "puñetazo*": 2, "punetazo*": 2,
    "zape": 1.5, "zarandea*": 2, "jaloneo*": 1.5, "jalone*": 1.5, "odio": 2, "odia*": 2,
    "miedo": 1, "peligro*": 1.5, "riesgo": 0.5, "preocupa*": 1, "alarma*": 1, "grave": 1.5, "graves": 1.5,
    "triste": 1, "tristeza": 1, "lamentable": 2, "insult*": 1.5, "ofens*": 1.5, "ofende": 1.5, "burla*": 1.5,
    "enoj*": 1.5, "furios*": 2, "furia": 2, "colera": 2, "iracund*": 2,
    "berrinche*": 2, "exabrupto*": 2, "arremet*": 1.5, "zafarrancho": 1.5, "trifulca": 1.5, "pleito*": 1,
    "empuj*": 1, "manotazo*": 2, "groseri*": 2, "grosero*": 2, "majader*": 2, "altercado*": 1.5,
    "basta": 1, "harto*": 2, "harta*": 2, "hartazgo": 2, "cansad*": 1, "asco": 2, "asqueros*": 2,
    # seguridad
    "violencia": 1.5, "violent*": 1.5, "inseguridad": 1.5, "insegur*": 1, "asesin*": 2, "homicidio*": 2,
    "masacre": 2, "muert*": 1, "desaparecid*": 1.5, "desaparicion*": 1.5, "secuestr*": 2, "feminicidio*": 2,
    "crimen": 1.5, "criminal*": 2, "delincuen*": 2, "cartel": 1, "carteles": 1, "huachicol*": 1.5,
    # insultos frecuentes en política mexicana y latinoamericana
    "corrupt*": 2, "ratero*": 2.5, "ratera*": 2.5, "ladron*": 2.5, "rata": 2, "ratas": 2, "roba*": 2, "robo": 2,
    "robos": 2, "robaron": 2, "saqueo": 2, "saque*": 2, "estafa*": 2, "estafador*": 2, "tranza*": 2, "transa": 2,
    "chapuc*": 1.5, "vendepatria*": 2.5, "lacayo*": 2, "titere*": 2, "pelele*": 2, "payaso*": 2, "payasa*": 2,
    "idiota*": 2.5, "imbecil*": 2.5, "estupid*": 2.5, "pendej*": 2.5, "tont*": 1.5, "ignorant*": 2,
    "nefast*": 2.5, "ruin": 2, "miserabl*": 2, "basura": 2, "porqueria*": 2, "cochinada*": 2, "pinche": 1.5,
    "maldit*": 1.5, "chairo*": 1, "fifi*": 0.5, "narcopresident*": 3, "narcogobierno*": 3, "narco*": 2,
    "dictadorzuel*": 2.5, "farsante*": 2.5, "fraude": 2, "fraudes": 2, "fraudulent*": 2, "peligro": 1.5,
    "lambiscon*": 1.5, "chayote*": 1.5, "chayoter*": 1.5, "zalamer*": 1, "vividor*": 2, "parasito*": 2,
}

# Frases que el análisis palabra por palabra no capta. Se buscan en el texto normalizado, antes de las reglas.
PHRASES: dict[str, float] = {
    "no sirve": -2, "no sirven": -2, "no sirvio": -2, "no hace nada": -2, "no ha hecho nada": -2,
    "no hizo nada": -2, "no hacen nada": -2, "no da una": -2, "no tiene idea": -2, "no sabe": -1,
    "que verguenza": -2.5, "que pena": -1.5, "que asco": -2.5, "que horror": -2, "ya basta": -2, "ni modo": -0.5,
    "se robo": -2.5, "se robaron": -2.5, "se lo robo": -2.5, "se burla": -2, "se burlan": -2, "da pena": -2,
    "da asco": -2.5, "da verguenza": -2.5, "da risa": -1.5, "da miedo": -1.5, "deja mucho que desear": -2,
    "conflicto de interes": -2, "conflicto de intereses": -2, "abuso de poder": -2.5, "uso electoral": -1.5,
    "baja aprobacion": -1.5, "cae la aprobacion": -1.5, "cae su aprobacion": -1.5, "pierde popularidad": -1.5,
    "en contra de": -0.5, "fuera de control": -2, "a la deriva": -2, "sin rumbo": -2, "mano dura": -0.5,
    "lo peor": -2, "el peor": -2, "la peor": -2, "nunca mas": -1.5, "hasta la madre": -2.5, "cero empatia": -2,
    "falta de": -1, "le falta": -1, "les falta": -1, "carece de": -1, "brilla por su ausencia": -2, "tomadura de pelo": -2, "pura grilla": -1.5,
    # pérdida de control: enojo, pleitos, berrinches
    "pierde los estribos": -2.5, "perdio los estribos": -2.5, "pierde la paciencia": -2,
    "perdio la paciencia": -2, "pierde el control": -2, "perdio el control": -2, "se le sale": -1,
    "se enoja": -2, "se enojo": -2, "se molesta": -1.5, "se molesto": -1.5, "se pone loco": -2,
    "encara a": -1.5, "encaro a": -1.5, "se lanza contra": -1.5, "arremete contra": -2, "la emprende contra": -2, "se le va encima": -2,
    "muy bien": 1.5, "buen trabajo": 2, "gran trabajo": 2, "bien hecho": 2, "sigue asi": 1.5, "vamos bien": 1,
    "estamos contigo": 2, "todo mi apoyo": 2, "mis respetos": 2, "a favor de": 0.5, "mano firme": 0.5,
}

SEVERE = [
    "corrupcion", "fraude", "soborno", "lavado", "desvio", "peculado", "delito", "detenido", "acoso", "narco",
    "enriquecimiento ilicito", "malversacion", "extorsion", "trafico de influencias", "nepotismo",
]

EMOJI: dict[str, float] = {
    "😡": -2, "🤬": -2.5, "😠": -2, "👎": -2, "💩": -2, "🤮": -2.5, "🤢": -2, "🤡": -2, "🐀": -2, "😤": -1.5,
    "🙄": -1.5, "😒": -1, "😢": -1, "😭": -1, "💔": -1.5, "😞": -1, "😔": -1, "🖕": -2.5, "🤦": -1.5, "😱": -1,
    "👏": 1.5, "❤": 1.5, "❤️": 1.5, "😍": 2, "🥰": 2, "👍": 1.5, "🙌": 1.5, "💪": 1.5, "🎉": 1.5, "😊": 1,
    "🙏": 0.5, "💯": 1, "✨": 0.5, "🇲🇽": 0.5,
}

# Hashtags: se busca la raíz dentro del texto pegado (#NarcoPresidenta → "narcopresidenta").
HASHTAG_NEG = ("fuera", "narco", "corrupt", "ratero", "ladron", "mentiros", "traidor", "renuncia", "nomas",
               "yabasta", "fraude", "dictador", "inept", "fracaso", "verguenza", "asesin", "basura", "odio")
HASHTAG_POS = ("todosconsheinbaum", "estamoscontigo", "orgullo", "gracias", "apoyo", "bravo", "vamos")

NEGATORS = {"no", "nunca", "jamas", "ni", "tampoco", "nada", "nadie", "ningun", "ninguno", "ninguna", "poco",
            "poca", "pocos", "pocas", "sin", "nunca"}
INTENSIFIERS = {"muy": 1.5, "tan": 1.5, "demasiado": 1.7, "demasiada": 1.7, "super": 1.5, "re": 1.3, "bien": 1.3,
                "totalmente": 1.7, "completamente": 1.7, "absolutamente": 1.8, "extremadamente": 1.8,
                "sumamente": 1.7, "realmente": 1.3, "verdaderamente": 1.4, "bastante": 1.3, "mas": 1.2,
                "increiblemente": 1.6, "tremendamente": 1.7, "terriblemente": 1.7, "puro": 1.3, "pura": 1.3,
                "toda": 1.2, "todo": 1.1, "enorme": 1.5, "brutal": 1.6, "pinche": 1.5}
# "lucha contra la corrupción", "cero impunidad": la palabra negativa no habla mal del objetivo.
NEUTRALIZERS = {"contra", "combate", "combatir", "combatimos", "combatira", "erradicar", "erradica", "cero",
                "anti", "acabar", "acabamos", "frenar", "frena", "castigo", "castigar", "sancionar"}
ATTENUATORS = {"algo": 0.6, "medio": 0.6, "casi": 0.7, "ligeramente": 0.5, "levemente": 0.5, "un": 1.0}
# Tras estas palabras la segunda parte de la oración pesa más y la primera menos.
ADVERSATIVES = ("pero", "sin embargo", "aunque", "no obstante", "mas bien", "en cambio", "aun asi")
NEGATION_WINDOW = 3
THRESHOLD = 0.2


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.lower())
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return " " + " ".join(re.sub(r"[^\w@#]+", " ", stripped).split()) + " "


def _split(lexicon: dict[str, float]) -> tuple[dict[str, float], list[tuple[str, float]]]:
    exact = {k: v for k, v in lexicon.items() if not k.endswith("*")}
    stems = sorted(((k[:-1], v) for k, v in lexicon.items() if k.endswith("*")), key=lambda kv: -len(kv[0]))
    return exact, stems


_POS_EXACT, _POS_STEMS = _split({normalize(k).strip(): v for k, v in POSITIVE.items() if not k.endswith("*")}
                                | {normalize(k[:-1]).strip() + "*": v for k, v in POSITIVE.items() if k.endswith("*")})
_NEG_EXACT, _NEG_STEMS = _split({normalize(k).strip(): v for k, v in NEGATIVE.items() if not k.endswith("*")}
                                | {normalize(k[:-1]).strip() + "*": v for k, v in NEGATIVE.items() if k.endswith("*")})
_PHRASES = sorted(((normalize(k).strip(), v) for k, v in PHRASES.items()), key=lambda kv: -len(kv[0]))
_ADVERSATIVE_RE = re.compile(r" (?:" + "|".join(ADVERSATIVES) + r") ")


def word_polarity(word: str) -> float:
    """Peso con signo de una palabra normalizada (0 si no está en el diccionario)."""
    word = word.lstrip("#")
    if word in _NEG_EXACT:
        return -_NEG_EXACT[word]
    if word in _POS_EXACT:
        return _POS_EXACT[word]
    for stem, weight in _NEG_STEMS:
        if word.startswith(stem):
            return -weight
    for stem, weight in _POS_STEMS:
        if word.startswith(stem):
            return weight
    return 0.0


def _hashtag_polarity(tag: str) -> float:
    body = tag.lstrip("#")
    if any(s in body for s in HASHTAG_NEG):
        return -2.0
    if any(s in body for s in HASHTAG_POS):
        return 1.5
    return word_polarity(body)


def _clause_score(clause: str) -> tuple[float, float]:
    """(suma positiva, suma negativa) de un fragmento normalizado, con frases, negación e intensidad."""
    pos = neg = 0.0
    for phrase, weight in _PHRASES:
        padded = f" {phrase} "
        while padded in clause:
            at = clause.index(padded)
            w = weight
            if any(x in NEGATORS for x in clause[:at].split()[-2:]):
                w = -w * (0.9 if w > 0 else 0.5)  # "no se enoja", "no hizo un buen trabajo"
            pos, neg = (pos + w, neg) if w > 0 else (pos, neg - w)
            clause = clause.replace(padded, " _ ", 1)  # las palabras de la frase no cuentan otra vez
    words = clause.split()
    for i, word in enumerate(words):
        polarity = _hashtag_polarity(word) if word.startswith("#") else word_polarity(word)
        if word in INTENSIFIERS and i + 1 < len(words) and word_polarity(words[i + 1]):
            continue  # "pinche", "puro"... valen como intensificadores si les sigue una palabra con peso
        if not polarity:
            continue
        before = words[max(0, i - NEGATION_WINDOW):i]
        for w in reversed(before[-2:]):
            if w in INTENSIFIERS:
                polarity *= INTENSIFIERS[w]
                break
            if w in ATTENUATORS:
                polarity *= ATTENUATORS[w]
                break
        if polarity < 0 and any(w in NEUTRALIZERS for w in before):
            continue
        if any(w in NEGATORS for w in before):
            # "no es bueno" es claramente negativo; "no es malo" solo es tibiamente positivo.
            polarity = -polarity * (0.9 if polarity > 0 else 0.5)
        if polarity > 0:
            pos += polarity
        else:
            neg -= polarity
    return pos, neg


def _accuses(text: str, term: str) -> bool:
    """El término grave aparece y no va tras "sin", "cero", "contra"... ("sin corrupción", "contra el lavado")."""
    for m in re.finditer(f" {term} ", text):
        before = [w for w in text[:m.start()].split()[-3:] if w not in ("el", "la", "los", "las", "de", "del")]
        if not before or (before[-1] != "sin" and before[-1] not in NEUTRALIZERS):
            return True
    return False


def _emoji_score(text: str) -> tuple[float, float]:
    pos = neg = 0.0
    for emoji, weight in EMOJI.items():
        if emoji == "❤️":
            continue  # ya lo cuenta "❤"
        n = text.count(emoji)
        pos, neg = (pos + n * weight, neg) if weight > 0 else (pos, neg - n * weight)
    return min(pos, 4.0), min(neg, 4.0)


def analyze(text: str) -> dict:
    t = normalize(text)
    pos = neg = 0.0
    for sentence in re.split(r"[.!?;\n]+", text):
        # Las comas cortan la negación ("No, es corrupta"); el "pero" cambia el peso del resto de la oración.
        early_p = early_n = late_p = late_n = 0.0
        turned = False
        for segment in re.split(r"[,:()\"“”«»]+", sentence):
            s = normalize(segment)
            if not turned and s.startswith((" aunque ", " si bien ")):
                p, n = _clause_score(s)  # concesiva: lo que importa viene después de la coma
                early_p, early_n, turned = early_p + p, early_n + n, True
                continue
            parts = [s] if turned else _ADVERSATIVE_RE.split(s, maxsplit=1)
            if len(parts) == 2:
                (p1, n1), (p2, n2) = _clause_score(f" {parts[0]} "), _clause_score(f" {parts[1]} ")
                early_p, early_n, late_p, late_n = early_p + p1, early_n + n1, late_p + p2, late_n + n2
                turned = True
            elif turned:
                p, n = _clause_score(s)
                late_p, late_n = late_p + p, late_n + n
            else:
                p, n = _clause_score(s)
                early_p, early_n = early_p + p, early_n + n
        if turned:
            pos += 0.6 * early_p + 1.4 * late_p
            neg += 0.6 * early_n + 1.4 * late_n
        else:
            pos, neg = pos + early_p, neg + early_n
    ep, en = _emoji_score(text)
    pos, neg = pos + ep, neg + en

    severe = [w for w in SEVERE if _accuses(t, w)]
    neg += 1.5 * len(severe)
    # Gritos: varias palabras en mayúsculas o "!!!" refuerzan el tono dominante.
    if len(re.findall(r"\b[A-ZÁÉÍÓÚÑ]{4,}\b", text)) >= 2 or "!!" in text:
        pos, neg = (pos * 1.2, neg) if pos > neg else (pos, neg * 1.2)

    total = pos + neg
    # El +1 suaviza: una sola palabra débil no llega a ±1, pero sí cruza el umbral.
    score = 0.0 if total == 0 else (pos - neg) / (total + 1)
    sentiment = "negative" if score <= -THRESHOLD else "positive" if score >= THRESHOLD else "neutral"
    return {
        "sentiment": sentiment,
        "score": round(score, 3),
        "severe_accusation": bool(severe),
        "topic": severe[0] if severe else None,
        "summary": None,
        "analyzer": "lexicon",
        # Señales encontradas en ambos sentidos o muy débiles: buenos candidatos para el análisis profundo.
        "ambiguous": sentiment == "neutral" and total > 0 or (pos > 0 and neg > 0 and abs(score) < 0.4),
    }
