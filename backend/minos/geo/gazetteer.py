"""Nomenclátor fuera de línea: países, estados de México y ciudades principales, con coordenadas aproximadas.

No se consulta ningún servicio de geocodificación: todo se resuelve aquí, sin costo ni envío de datos a terceros.
Cada nombre puede marcarse como:
- estricto ("strict"): abreviatura que solo vale en un campo de ubicación ("N.L.", "Jal."), nunca en el texto libre,
  donde "son", "col" o "ver" son palabras comunes;
- ambiguo ("ambiguous"): también es apellido, nombre o palabra común (Guerrero, Hidalgo, León, Chile); en el texto
  solo cuenta con contexto ("en Hidalgo", "estado de Guerrero").
"""
from dataclasses import dataclass

from ..domain.targets import normalize


@dataclass(frozen=True)
class GazetteerEntry:
    country: str  # ISO 3166-1 alfa-2
    region: str | None  # ISO 3166-2 ("MX-NLE"), solo en México
    city: str | None
    lat: float
    lon: float

    @property
    def precision(self) -> str:
        return "city" if self.city else "region" if self.region else "country"


# código, nombre en español, otros nombres (los que empiezan con "~" son ambiguos), latitud, longitud
COUNTRIES: list[tuple[str, str, list[str], float, float]] = [
    ("MX", "México", ["Mexico", "Estados Unidos Mexicanos", "República Mexicana"], 23.63, -102.55),
    ("US", "Estados Unidos", ["EE.UU.", "EE. UU.", "EEUU", "EUA", "USA", "U.S.A.", "United States", "Estados Unidos de América", "Unión Americana"], 39.83, -98.58),
    ("CA", "Canadá", ["Canada"], 56.13, -106.35),
    ("GT", "Guatemala", [], 15.78, -90.23),
    ("BZ", "Belice", ["Belize"], 17.19, -88.50),
    ("SV", "El Salvador", [], 13.79, -88.90),
    ("HN", "Honduras", [], 15.20, -86.24),
    ("NI", "Nicaragua", [], 12.87, -85.21),
    ("CR", "Costa Rica", [], 9.75, -83.75),
    ("PA", "Panamá", ["Panama"], 8.54, -80.78),
    ("CU", "Cuba", [], 21.52, -77.78),
    ("DO", "República Dominicana", ["Dominican Republic"], 18.74, -70.16),
    ("PR", "Puerto Rico", [], 18.22, -66.59),
    ("HT", "Haití", ["Haiti"], 18.97, -72.29),
    ("CO", "Colombia", [], 4.57, -74.30),
    ("VE", "Venezuela", [], 6.42, -66.59),
    ("EC", "Ecuador", [], -1.83, -78.18),
    ("PE", "Perú", ["Peru"], -9.19, -75.02),
    ("BO", "Bolivia", [], -16.29, -63.59),
    ("CL", "Chile", ["~Chile"], -35.68, -71.54),
    ("AR", "Argentina", [], -38.42, -63.62),
    ("UY", "Uruguay", [], -32.52, -55.77),
    ("PY", "Paraguay", [], -23.44, -58.44),
    ("BR", "Brasil", ["Brazil"], -14.24, -51.93),
    ("ES", "España", ["Spain"], 40.46, -3.75),
    ("PT", "Portugal", [], 39.40, -8.22),
    ("FR", "Francia", ["France"], 46.23, 2.21),
    ("DE", "Alemania", ["Germany"], 51.17, 10.45),
    ("IT", "Italia", ["Italy"], 41.87, 12.57),
    ("GB", "Reino Unido", ["Inglaterra", "Gran Bretaña", "United Kingdom", "UK", "England"], 54.0, -2.0),
    ("IE", "Irlanda", ["Ireland"], 53.41, -8.24),
    ("NL", "Países Bajos", ["Holanda", "Netherlands"], 52.13, 5.29),
    ("BE", "Bélgica", ["Belgium"], 50.50, 4.47),
    ("CH", "Suiza", ["Switzerland"], 46.82, 8.23),
    ("AT", "Austria", [], 47.52, 14.55),
    ("SE", "Suecia", ["Sweden"], 60.13, 18.64),
    ("NO", "Noruega", ["Norway"], 60.47, 8.47),
    ("PL", "Polonia", ["Poland"], 51.92, 19.15),
    ("UA", "Ucrania", ["Ukraine"], 48.38, 31.17),
    ("RU", "Rusia", ["Russia"], 61.52, 105.32),
    ("TR", "Turquía", ["Turkey", "Türkiye"], 38.96, 35.24),
    ("IL", "Israel", ["~Israel"], 31.05, 34.85),
    ("PS", "Palestina", ["Gaza", "Franja de Gaza", "Cisjordania"], 31.95, 35.23),
    ("IR", "Irán", ["Iran"], 32.43, 53.69),
    ("SA", "Arabia Saudita", ["Arabia Saudí", "Saudi Arabia"], 23.89, 45.08),
    ("AE", "Emiratos Árabes Unidos", ["Emiratos Árabes", "UAE"], 23.42, 53.85),
    ("EG", "Egipto", ["Egypt"], 26.82, 30.80),
    ("MA", "Marruecos", ["Morocco"], 31.79, -7.09),
    ("ZA", "Sudáfrica", ["South Africa"], -30.56, 22.94),
    ("NG", "Nigeria", [], 9.08, 8.68),
    ("CN", "China", ["~China"], 35.86, 104.20),
    ("JP", "Japón", ["Japan"], 36.20, 138.25),
    ("KR", "Corea del Sur", ["South Korea"], 35.91, 127.77),
    ("KP", "Corea del Norte", ["North Korea"], 40.34, 127.51),
    ("IN", "India", [], 20.59, 78.96),
    ("AU", "Australia", [], -25.27, 133.78),
    ("NZ", "Nueva Zelanda", ["New Zealand"], -40.90, 174.89),
    ("VN", "Vietnam", [], 14.06, 108.28),
    ("PH", "Filipinas", ["Philippines"], 12.88, 121.77),
]

# Estados de México: código ISO 3166-2, nombre, otros nombres ("~" ambiguo, "!" abreviatura estricta), centro.
# Cuando la capital se llama igual que el estado (Puebla, Oaxaca, Chihuahua…) el nombre resuelve al estado.
MX_STATES: list[tuple[str, str, list[str], float, float]] = [
    ("MX-AGU", "Aguascalientes", ["!Ags"], 22.04, -102.35),
    ("MX-BCN", "Baja California", ["!BC", "!B.C."], 30.34, -115.21),
    ("MX-BCS", "Baja California Sur", ["!BCS", "!B.C.S."], 25.07, -111.45),
    ("MX-CAM", "Campeche", ["!Camp"], 18.66, -90.28),
    ("MX-CHP", "Chiapas", ["!Chis"], 16.53, -92.58),
    ("MX-CHH", "Chihuahua", ["!Chih"], 28.97, -106.23),
    ("MX-CMX", "Ciudad de México", ["CDMX", "Distrito Federal", "México D.F.", "Mexico City", "!DF", "!D.F.", "Capital del país"], 19.33, -99.14),
    ("MX-COA", "Coahuila", ["Coahuila de Zaragoza", "!Coah"], 27.45, -101.89),
    ("MX-COL", "Colima", ["!Col"], 19.13, -103.92),
    ("MX-DUR", "Durango", ["!Dgo"], 24.57, -104.81),
    ("MX-GUA", "Guanajuato", ["!Gto"], 20.81, -100.90),
    ("MX-GRO", "Guerrero", ["~Guerrero", "!Gro"], 17.76, -100.09),
    ("MX-HID", "Hidalgo", ["~Hidalgo", "!Hgo"], 20.54, -98.92),
    ("MX-JAL", "Jalisco", ["!Jal"], 20.30, -103.60),
    ("MX-MEX", "Estado de México", ["Edomex", "Edo. Méx.", "Edo Mex", "Edo. de México", "!Méx"], 19.33, -99.74),
    ("MX-MIC", "Michoacán", ["Michoacán de Ocampo", "!Mich"], 19.25, -101.94),
    ("MX-MOR", "Morelos", ["~Morelos", "!Mor"], 18.74, -99.08),
    ("MX-NAY", "Nayarit", ["!Nay"], 21.79, -104.82),
    ("MX-NLE", "Nuevo León", ["!NL", "!N.L.", "!N. L."], 25.62, -99.83),
    ("MX-OAX", "Oaxaca", ["!Oax"], 16.94, -96.21),
    ("MX-PUE", "Puebla", ["!Pue"], 18.55, -97.89),
    ("MX-QUE", "Querétaro", ["Santiago de Querétaro", "!Qro"], 20.74, -99.97),
    ("MX-ROO", "Quintana Roo", ["!Q. Roo", "!QRoo", "!Q.R."], 19.39, -88.34),
    ("MX-SLP", "San Luis Potosí", ["!SLP", "!S.L.P."], 22.45, -100.32),
    ("MX-SIN", "Sinaloa", ["!Sin"], 25.60, -108.00),
    ("MX-SON", "Sonora", ["!Son"], 29.53, -110.49),
    ("MX-TAB", "Tabasco", ["!Tab"], 18.13, -92.83),
    ("MX-TAM", "Tamaulipas", ["!Tamps"], 24.08, -98.52),
    ("MX-TLA", "Tlaxcala", ["!Tlax"], 19.40, -98.16),
    ("MX-VER", "Veracruz", ["Veracruz de Ignacio de la Llave", "!Ver"], 19.09, -96.60),
    ("MX-YUC", "Yucatán", ["!Yuc"], 20.66, -88.98),
    ("MX-ZAC", "Zacatecas", ["!Zac"], 23.38, -102.58),
]

# Ciudades: nombre, país, estado (solo México), otros nombres ("~" ambiguo, "!" estricto), latitud, longitud.
CITIES: list[tuple[str, str, str | None, list[str], float, float]] = [
    # México
    ("Guadalajara", "MX", "MX-JAL", ["GDL"], 20.66, -103.35),
    ("Zapopan", "MX", "MX-JAL", [], 20.72, -103.39),
    ("Tlaquepaque", "MX", "MX-JAL", ["San Pedro Tlaquepaque"], 20.64, -103.29),
    ("Puerto Vallarta", "MX", "MX-JAL", [], 20.65, -105.23),
    ("Monterrey", "MX", "MX-NLE", ["MTY", "Área metropolitana de Monterrey"], 25.69, -100.32),
    ("San Pedro Garza García", "MX", "MX-NLE", ["San Pedro Garza Garcia"], 25.66, -100.40),
    ("Tijuana", "MX", "MX-BCN", ["TJ"], 32.51, -117.04),
    ("Mexicali", "MX", "MX-BCN", [], 32.62, -115.45),
    ("Ensenada", "MX", "MX-BCN", [], 31.87, -116.60),
    ("La Paz", "MX", "MX-BCS", ["~La Paz"], 24.14, -110.31),
    ("Los Cabos", "MX", "MX-BCS", ["Cabo San Lucas", "San José del Cabo"], 22.89, -109.92),
    ("Hermosillo", "MX", "MX-SON", ["~Hermosillo"], 29.07, -110.96),
    ("Ciudad Obregón", "MX", "MX-SON", ["Cd. Obregón"], 27.48, -109.93),
    ("Nogales", "MX", "MX-SON", [], 31.31, -110.94),
    ("Ciudad Juárez", "MX", "MX-CHH", ["Cd. Juárez", "Juárez, Chihuahua", "~Juárez"], 31.69, -106.42),
    ("Saltillo", "MX", "MX-COA", [], 25.42, -101.01),
    ("Torreón", "MX", "MX-COA", [], 25.54, -103.41),
    ("Monclova", "MX", "MX-COA", [], 26.91, -101.42),
    ("Piedras Negras", "MX", "MX-COA", [], 28.70, -100.52),
    ("Reynosa", "MX", "MX-TAM", [], 26.05, -98.30),
    ("Matamoros", "MX", "MX-TAM", ["~Matamoros"], 25.87, -97.50),
    ("Nuevo Laredo", "MX", "MX-TAM", [], 27.48, -99.55),
    ("Tampico", "MX", "MX-TAM", [], 22.23, -97.86),
    ("Ciudad Victoria", "MX", "MX-TAM", ["Cd. Victoria"], 23.74, -99.14),
    ("Culiacán", "MX", "MX-SIN", [], 24.81, -107.39),
    ("Mazatlán", "MX", "MX-SIN", [], 23.25, -106.41),
    ("Los Mochis", "MX", "MX-SIN", [], 25.79, -108.99),
    ("Tepic", "MX", "MX-NAY", [], 21.50, -104.89),
    ("León", "MX", "MX-GUA", ["~León", "León, Guanajuato"], 21.13, -101.69),
    ("Irapuato", "MX", "MX-GUA", [], 20.68, -101.36),
    ("Celaya", "MX", "MX-GUA", [], 20.52, -100.82),
    ("Morelia", "MX", "MX-MIC", [], 19.71, -101.20),
    ("Uruapan", "MX", "MX-MIC", [], 19.42, -102.05),
    ("Toluca", "MX", "MX-MEX", [], 19.28, -99.66),
    ("Ecatepec", "MX", "MX-MEX", [], 19.60, -99.05),
    ("Naucalpan", "MX", "MX-MEX", [], 19.48, -99.24),
    ("Nezahualcóyotl", "MX", "MX-MEX", ["Ciudad Nezahualcóyotl", "Neza", "~Nezahualcóyotl"], 19.40, -99.01),
    ("Cuernavaca", "MX", "MX-MOR", [], 18.92, -99.22),
    ("Pachuca", "MX", "MX-HID", [], 20.10, -98.76),
    ("Acapulco", "MX", "MX-GRO", [], 16.85, -99.82),
    ("Chilpancingo", "MX", "MX-GRO", [], 17.55, -99.50),
    ("Xalapa", "MX", "MX-VER", ["Jalapa"], 19.54, -96.91),
    ("Coatzacoalcos", "MX", "MX-VER", [], 18.13, -94.46),
    ("Córdoba", "MX", "MX-VER", [], 18.88, -96.93),
    ("Villahermosa", "MX", "MX-TAB", [], 17.99, -92.95),
    ("Tuxtla Gutiérrez", "MX", "MX-CHP", ["Tuxtla"], 16.75, -93.12),
    ("San Cristóbal de las Casas", "MX", "MX-CHP", [], 16.74, -92.64),
    ("Tapachula", "MX", "MX-CHP", [], 14.90, -92.26),
    ("Mérida", "MX", "MX-YUC", [], 20.97, -89.59),
    ("Cancún", "MX", "MX-ROO", [], 21.16, -86.85),
    ("Playa del Carmen", "MX", "MX-ROO", [], 20.63, -87.07),
    ("Chetumal", "MX", "MX-ROO", [], 18.50, -88.30),
    ("Ciudad del Carmen", "MX", "MX-CAM", [], 18.65, -91.81),
    ("Manzanillo", "MX", "MX-COL", [], 19.05, -104.32),
    ("Fresnillo", "MX", "MX-ZAC", [], 23.18, -102.87),
    ("Tehuacán", "MX", "MX-PUE", [], 18.46, -97.39),
    ("Juchitán", "MX", "MX-OAX", [], 16.43, -95.02),
    ("Iztapalapa", "MX", "MX-CMX", [], 19.36, -99.09),
    ("Coyoacán", "MX", "MX-CMX", [], 19.35, -99.16),
    ("Tlalpan", "MX", "MX-CMX", [], 19.29, -99.16),
    ("Xochimilco", "MX", "MX-CMX", [], 19.26, -99.11),
    ("Gustavo A. Madero", "MX", "MX-CMX", [], 19.48, -99.11),
    # Resto del mundo
    ("Madrid", "ES", None, [], 40.42, -3.70),
    ("Barcelona", "ES", None, [], 41.39, 2.17),
    ("Sevilla", "ES", None, [], 37.39, -5.98),
    ("Valencia", "ES", None, ["~Valencia"], 39.47, -0.38),
    ("Guadalajara", "ES", None, [], 40.63, -3.17),
    ("León", "ES", None, ["~León"], 42.60, -5.57),
    ("Mérida", "ES", None, [], 38.92, -6.34),
    ("Córdoba", "ES", None, [], 37.89, -4.78),
    ("Bogotá", "CO", None, [], 4.71, -74.07),
    ("Medellín", "CO", None, [], 6.24, -75.58),
    ("Cali", "CO", None, [], 3.45, -76.53),
    ("Buenos Aires", "AR", None, [], -34.60, -58.38),
    ("Córdoba", "AR", None, [], -31.42, -64.19),
    ("Santiago de Chile", "CL", None, ["~Santiago"], -33.45, -70.67),
    ("Lima", "PE", None, ["~Lima"], -12.05, -77.04),
    ("Caracas", "VE", None, [], 10.48, -66.90),
    ("Maracaibo", "VE", None, [], 10.64, -71.61),
    ("Mérida", "VE", None, [], 8.59, -71.16),
    ("Valencia", "VE", None, ["~Valencia"], 10.16, -68.01),
    ("Quito", "EC", None, [], -0.18, -78.47),
    ("Guayaquil", "EC", None, [], -2.17, -79.92),
    ("La Paz", "BO", None, ["~La Paz"], -16.49, -68.12),
    ("Santa Cruz de la Sierra", "BO", None, [], -17.81, -63.16),
    ("Asunción", "PY", None, [], -25.26, -57.58),
    ("Montevideo", "UY", None, [], -34.90, -56.16),
    ("La Habana", "CU", None, ["Habana", "Havana"], 23.11, -82.37),
    ("San José", "CR", None, ["~San José"], 9.93, -84.09),
    ("Ciudad de Guatemala", "GT", None, ["Guatemala City"], 14.63, -90.51),
    ("San Salvador", "SV", None, [], 13.69, -89.22),
    ("Tegucigalpa", "HN", None, [], 14.07, -87.19),
    ("San Pedro Sula", "HN", None, [], 15.50, -88.03),
    ("Managua", "NI", None, [], 12.12, -86.24),
    ("Ciudad de Panamá", "PA", None, ["Panama City"], 8.98, -79.52),
    ("Santo Domingo", "DO", None, [], 18.49, -69.93),
    ("San Juan", "PR", None, ["~San Juan"], 18.47, -66.11),
    ("Washington", "US", None, ["~Washington", "Washington D.C.", "Washington DC"], 38.91, -77.04),
    ("Nueva York", "US", None, ["New York", "NYC", "!NY"], 40.71, -74.01),
    ("Los Ángeles", "US", None, ["Los Angeles", "!LA", "!L.A."], 34.05, -118.24),
    ("Miami", "US", None, [], 25.76, -80.19),
    ("Houston", "US", None, [], 29.76, -95.37),
    ("Dallas", "US", None, [], 32.78, -96.80),
    ("San Antonio", "US", None, ["~San Antonio"], 29.42, -98.49),
    ("Chicago", "US", None, [], 41.88, -87.63),
    ("Phoenix", "US", None, [], 33.45, -112.07),
    ("San Diego", "US", None, [], 32.72, -117.16),
    ("El Paso", "US", None, [], 31.76, -106.49),
    ("San Francisco", "US", None, ["~San Francisco"], 37.77, -122.42),
    ("Las Vegas", "US", None, [], 36.17, -115.14),
    ("Atlanta", "US", None, [], 33.75, -84.39),
    ("Toronto", "CA", None, [], 43.65, -79.38),
    ("Montreal", "CA", None, ["Montréal"], 45.50, -73.57),
    ("Vancouver", "CA", None, [], 49.28, -123.12),
    ("Londres", "GB", None, ["London"], 51.51, -0.13),
    ("París", "FR", None, ["~Paris"], 48.86, 2.35),
    ("Roma", "IT", None, ["~Roma", "Rome"], 41.90, 12.50),
    ("Berlín", "DE", None, ["Berlin"], 52.52, 13.41),
    ("Bruselas", "BE", None, ["Brussels"], 50.85, 4.35),
    ("Ginebra", "CH", None, ["Geneva"], 46.20, 6.14),
    ("Viena", "AT", None, ["Vienna"], 48.21, 16.37),
    ("Lisboa", "PT", None, ["Lisbon"], 38.72, -9.14),
    ("Ámsterdam", "NL", None, ["Amsterdam"], 52.37, 4.90),
    ("Moscú", "RU", None, ["Moscow"], 55.76, 37.62),
    ("Kiev", "UA", None, ["Kyiv", "Kiiv"], 50.45, 30.52),
    ("Jerusalén", "IL", None, ["Jerusalem"], 31.77, 35.21),
    ("Tel Aviv", "IL", None, [], 32.09, 34.78),
    ("Pekín", "CN", None, ["Beijing"], 39.90, 116.41),
    ("Shanghái", "CN", None, ["Shanghai"], 31.23, 121.47),
    ("Tokio", "JP", None, ["Tokyo"], 35.68, 139.65),
    ("Seúl", "KR", None, ["Seoul"], 37.57, 126.98),
    ("Nueva Delhi", "IN", None, ["New Delhi"], 28.61, 77.21),
    ("Dubái", "AE", None, ["Dubai"], 25.20, 55.27),
    ("Estambul", "TR", None, ["Istanbul"], 41.01, 28.98),
]


@dataclass(frozen=True)
class Name:
    entry: GazetteerEntry
    strict: bool
    ambiguous: bool


COUNTRY_NAMES = {code: name for code, name, *_ in COUNTRIES}
REGION_NAMES = {code: name for code, name, *_ in MX_STATES}
COUNTRY_ENTRIES = {code: GazetteerEntry(code, None, None, lat, lon) for code, _, _, lat, lon in COUNTRIES}
REGION_ENTRIES = {code: GazetteerEntry("MX", code, None, lat, lon) for code, _, _, lat, lon in MX_STATES}


def key(value: str) -> tuple[str, ...]:
    """Nombre normalizado en palabras: "N.L." → ("n", "l"), "Ciudad Juárez" → ("ciudad", "juarez"), "#CDMX" → ("cdmx",)."""
    return tuple(w for w in (w.lstrip("#") for w in normalize(value).split()) if w)


def _build() -> dict[tuple[str, ...], list[Name]]:
    index: dict[tuple[str, ...], list[Name]] = {}

    def add(raw: str, entry: GazetteerEntry, *, ambiguous_default: bool = False) -> None:
        strict, ambiguous = raw.startswith("!"), raw.startswith("~") or ambiguous_default
        k = key(raw.lstrip("!~"))
        if not k:
            return
        names = index.setdefault(k, [])
        same = next((n for n in names if n.entry == entry), None)
        if same is not None:
            # "Guerrero" aparece como nombre y como "~Guerrero": gana la marca más restrictiva.
            if (strict and not same.strict) or (ambiguous and not same.ambiguous):
                names[names.index(same)] = Name(entry, same.strict or strict, same.ambiguous or ambiguous)
            return
        names.append(Name(entry, strict, ambiguous))

    for code, name, others, *_ in COUNTRIES:
        for raw in [name, *others]:
            add(raw, COUNTRY_ENTRIES[code])
    for code, name, others, *_ in MX_STATES:
        for raw in [name, *others]:
            add(raw, REGION_ENTRIES[code])
    for name, country, region, others, lat, lon in CITIES:
        entry = GazetteerEntry(country, region, name, lat, lon)
        for raw in [name, *others]:
            add(raw, entry)
    return index


INDEX = _build()
MAX_WORDS = max(len(k) for k in INDEX)


def place_label(country: str, region: str | None, city: str | None) -> str:
    """"Monterrey, Nuevo León", "Madrid, España", "Jalisco" o "Chile"."""
    country_name = COUNTRY_NAMES.get(country, country)
    if city:
        return f"{city}, {REGION_NAMES[region] if region in REGION_NAMES else country_name}"
    return REGION_NAMES.get(region or "", country_name)
