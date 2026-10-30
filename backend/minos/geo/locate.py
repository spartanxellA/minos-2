"""Ubicación de cada mención, de la pista más confiable a la menos confiable.

1. geotag: la publicación trae coordenada o lugar etiquetado (X, muy pocas veces).
2. profile: ubicación del perfil del autor o país del canal (X, YouTube).
3. community: comunidad con nombre de lugar (r/mexico, r/Monterrey).
4. outlet: ciudad o país del medio que publicó la nota (RSS / Google Noticias).
5. text: el lugar que más se nombra en el texto; dice de dónde trata la nota, no desde dónde se escribió.
"""
from dataclasses import dataclass

from ..config import GeoSettings
from ..domain.mentions import GeoHint, MentionDraft
from .gazetteer import COUNTRY_ENTRIES, GazetteerEntry
from .outlets import locate_outlet
from .resolver import resolve_location, resolve_text

METHODS = ("geotag", "profile", "community", "outlet", "text")


@dataclass(frozen=True)
class Located:
    country: str
    region: str | None
    city: str | None
    lat: float
    lon: float
    precision: str  # "point", "city", "region" o "country"
    method: str

    @classmethod
    def of(cls, entry: GazetteerEntry, method: str) -> "Located":
        return cls(entry.country, entry.region, entry.city, entry.lat, entry.lon, entry.precision, method)


def _from_hint(hint: GeoHint, default_country: str) -> Located | None:
    if hint.lat is not None and hint.lon is not None:
        entry = resolve_location(hint.place, default_country)
        country = (hint.country_code or (entry.country if entry else "")).upper()
        if country:
            same = entry is not None and entry.country == country
            return Located(country, entry.region if same else None, entry.city if same else None,
                           hint.lat, hint.lon, "point", "geotag")
    if hint.place and (entry := resolve_location(hint.place, (hint.country_code or default_country).upper())):
        return Located.of(entry, "geotag")
    if entry := resolve_location(hint.author_location, default_country):
        return Located.of(entry, "profile")
    if hint.country_code and (entry := COUNTRY_ENTRIES.get(hint.country_code.upper())):
        return Located.of(entry, "profile")
    if entry := resolve_location(hint.community, default_country):
        return Located.of(entry, "community")
    if (hint.outlet_url or hint.outlet_name) and (
        entry := locate_outlet(hint.outlet_url, hint.outlet_name, default_country)
    ):
        return Located.of(entry, "outlet")
    return None


def locate(hint: GeoHint | None, text: str, target_names: list[str], settings: GeoSettings) -> Located | None:
    if not settings.enabled:
        return None
    if hint is not None and (found := _from_hint(hint, settings.default_country)):
        return found
    if settings.from_text and (entry := resolve_text(text, target_names, settings.default_country)):
        return Located.of(entry, "text")
    return None


def locate_draft(draft: MentionDraft, target_names: list[str], settings: GeoSettings) -> Located | None:
    return locate(draft.geo, draft.text, target_names, settings)
