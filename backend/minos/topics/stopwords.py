"""Palabras vacías en español, inglés y francés, más el ruido típico de redes. Van en minúsculas y sin acentos:
se comparan contra la palabra ya normalizada, así «está», «esta» y «ESTÁ» caen igual."""
import unicodedata

_ES = """
a acá aca ahi ahí al algo algun alguna algunas alguno algunos alla allá alli allí ante antes aquel aquella aquellas
aquello aquellos aqui aquí asi así aun aún aunque bajo bien cada casi como cómo con contra cual cuál cuales cuando
cuándo cuanto cuánto cuantos de del desde donde dónde dos el él ella ellas ello ellos en entre era eran eres es esa
esas ese eso esos esta está estaba estaban estamos estan están estar estas este esto estos estoy fue fueron
fui ha haber había habia han has hasta hay haya he hemos hizo hace hacen hacer hacia hoy la las le les lo los mas más
me mi mis mía mio mío mucho muchos muy nada ni ningun ninguna no nos nosotros nuestra nuestro nuestros o otra otras
otro otros para pero poco por porque que qué quien quién quienes se sea sean según segun ser si sí sido siempre sin
sino sobre solo sólo son soy su sus suya suyo tal también tambien tan tanto te tenemos tener tengo tiene tienen todo
todos toda todas tras tu tú tus un una uno unos unas usted ustedes va vamos van ya yo eh pues dice dijo dicen ver
vez veces cosa cosas año años dia día dias días hoy ayer mañana manana ahora luego aqui solo sólo puede pueden
podría podria tenía tenia tiene sera será serán seran ser estará estara sigue mismo misma mismos ademas además
durante mientras menos nunca otra parte tras través traves sus gran grandes buen buena mejor
gracias hola favor creo hecho habla hablan hablar hablando según dicho
"""

_EN = """
a about above after again against all also am an and any are aren't as at be because been before being below
between both but by can can't cannot could couldn't did didn't do does doesn't doing don't down during each few for
from further had hadn't has hasn't have haven't having he her here hers herself him himself his how i if in into is
isn't it it's its itself just let's me more most my myself no nor not now of off on once only or other our ours
ourselves out over own same she should so some such than that that's the their theirs them themselves then there
these they this those through to too under until up very was wasn't we were weren't what when where which while who
whom why will with won't would you your yours yourself yourselves get got gets one two new like said says say will
just can also would could people time today year years day days week now really still even back much many make made
know think going want need see way well yes yeah via
"""

_FR = """
a à afin ai aie aient ainsi alors au aucun aucune aujourd aujourdhui auprès aussi autre autres aux avait avant avec
avoir ayant bien ça car ce ceci cela celle celles celui cependant ces cet cette ceux chaque chez ci comme comment
dans de des depuis donc dont du elle elles en encore entre es est et étaient était été être eu eux fait faire fois
font hors ici il ils je jusqu jusque la là le les leur leurs lui ma mais me même mêmes mes moi mon ne ni non nos
notre nous on ont ou où par parce pas peu peut plus pour pourquoi qu quand que quel quelle quelles quels qui quoi
sa sans se selon ses si sien soit son sont sous sur ta tandis te tes toi ton tous tout toute toutes très tu un une
vers voici voilà vos votre vous y ans an jour jours après déjà deja dit dire fait faut etre tres aussi encore
"""

# Lo que aparece en cualquier publicación y no dice de qué se habla.
_SOCIAL = """
rt via http https www com org net html amp gt lt nbsp jaja jajaja jajajaja jeje lol lmao omg xd mdr ptdr
video foto fotos thread hilo link enlace click aqui lee leer more mas info nota url pic status
"""


def fold(word: str) -> str:
    """Minúsculas y sin acentos (la ñ se queda: «año» no es «ano»)."""
    word = word.lower().replace("ñ", "\0")
    word = "".join(c for c in unicodedata.normalize("NFD", word) if unicodedata.category(c) != "Mn")
    return word.replace("\0", "ñ")


STOPWORDS: frozenset[str] = frozenset(fold(w) for block in (_ES, _EN, _FR, _SOCIAL) for w in block.split())
