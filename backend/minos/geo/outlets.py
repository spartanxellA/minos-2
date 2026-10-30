"""Dónde está la redacción de un medio: por su dominio conocido, por su nombre o por el dominio de país."""
import re
from urllib.parse import urlparse

from .gazetteer import COUNTRY_ENTRIES, INDEX, GazetteerEntry
from .resolver import resolve_location, resolve_text

_CDMX = "Ciudad de México"

# Medios con redacción conocida. Se dejan fuera los que tienen ediciones en varios países bajo el mismo dominio
# (Infobae, El País, CNN, BBC): ahí el dominio no dice de dónde sale la nota.
KNOWN_OUTLETS: dict[str, str] = {
    "eluniversal.com.mx": _CDMX, "milenio.com": _CDMX, "reforma.com": _CDMX, "jornada.com.mx": _CDMX,
    "excelsior.com.mx": _CDMX, "elfinanciero.com.mx": _CDMX, "eleconomista.com.mx": _CDMX, "proceso.com.mx": _CDMX,
    "animalpolitico.com": _CDMX, "sdpnoticias.com": _CDMX, "aristeguinoticias.com": _CDMX, "latinus.us": _CDMX,
    "elsoldemexico.com.mx": _CDMX, "lasillarota.com": _CDMX, "nmas.com.mx": _CDMX, "tvazteca.com": _CDMX,
    "radioformula.com.mx": _CDMX, "expansion.mx": _CDMX, "elheraldodemexico.com": _CDMX, "razon.com.mx": _CDMX,
    "cronica.com.mx": _CDMX, "contralinea.com.mx": _CDMX, "politico.mx": _CDMX, "forbes.com.mx": _CDMX,
    "elnorte.com": "Monterrey", "abcnoticias.mx": "Monterrey", "info7.mx": "Monterrey", "elhorizonte.mx": "Monterrey",
    "informador.mx": "Guadalajara", "mural.com": "Guadalajara",
    "elsiglodetorreon.com.mx": "Torreón", "vanguardia.com.mx": "Saltillo", "zocalo.com.mx": "Saltillo",
    "diariodeyucatan.com": "Mérida", "am.com.mx": "León", "elimparcial.com": "Hermosillo",
    "noroeste.com.mx": "Culiacán", "diario.mx": "Ciudad Juárez", "elheraldodechihuahua.com.mx": "Chihuahua",
    "e-consulta.com": "Puebla", "quadratin.com.mx": "Morelia", "diariodexalapa.com.mx": "Xalapa",
    "zetatijuana.com": "Tijuana", "frontera.info": "Tijuana",
    "novedadesqroo.com.mx": "Cancún", "imagenradio.com.mx": _CDMX,
}

# Dominios de país. ".co" y ".us" se usan también como genéricos; solo cuenta ".com.co".
_TLD = {
    "mx": "MX", "ar": "AR", "com.co": "CO", "cl": "CL", "pe": "PE", "ve": "VE", "ec": "EC", "bo": "BO", "py": "PY",
    "uy": "UY", "gt": "GT", "sv": "SV", "hn": "HN", "ni": "NI", "cr": "CR", "pa": "PA", "do": "DO", "cu": "CU",
    "pr": "PR", "es": "ES", "pt": "PT", "fr": "FR", "de": "DE", "it": "IT", "br": "BR", "uk": "GB", "ca": "CA",
}
# Familia "El Sol de …" de la OEM y otros periódicos que llevan la ciudad en el dominio.
_CITY_IN_DOMAIN = re.compile(r"^(?:elsolde|diariode|elheraldode|noticiasde)([a-z]+)\.")


def _host(url: str | None) -> str:
    if not url:
        return ""
    host = (urlparse(url if "//" in url else f"//{url}").hostname or "").lower()
    return host.removeprefix("www.")


def locate_outlet(url: str | None, name: str | None, default_country: str = "MX") -> GazetteerEntry | None:
    host = _host(url)
    for domain, city in KNOWN_OUTLETS.items():
        if host == domain or host.endswith("." + domain):
            return resolve_location(city, "MX")
    if m := _CITY_IN_DOMAIN.match(host):
        # "elsoldetampico.com.mx" → "tampico"; solo si el nombre pegado es una ciudad o un estado conocido.
        glued = m.group(1)
        for k, names in INDEX.items():
            if "".join(k) == glued and not any(n.strict for n in names):
                return next((n.entry for n in names if n.entry.country == default_country), names[0].entry)
    if name and (found := resolve_text(name, default_country=default_country, lenient=True)):
        return found
    for tld, country in _TLD.items():
        if host.endswith("." + tld):
            return COUNTRY_ENTRIES.get(country)
    return None

