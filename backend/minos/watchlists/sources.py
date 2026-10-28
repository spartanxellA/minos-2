"""Lectores de cada lista oficial y de las listas propias (CSV).

Cada lector recibe el archivo tal como se descargó y devuelve registros ya normalizados. Los formatos son los que
publica cada autoridad; si cambian, el lector falla con un mensaje claro y el error aparece en el panel de listas.
"""
import csv
import hashlib
import io
import itertools
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import timedelta

from ..domain.screening import EntryKind, WatchlistRecord, ascii_fold


class Category:
    SANCTIONS = "sanctions"
    PEP = "pep"
    TAX = "tax"
    DEBARMENT = "debarment"
    OTHER = "other"


CATEGORY_LABEL = {
    Category.SANCTIONS: "Sanciones", Category.PEP: "Persona políticamente expuesta", Category.TAX: "Fiscal (SAT)",
    Category.DEBARMENT: "Inhabilitación", Category.OTHER: "Otra",
}

Parser = Callable[[bytes, str], Iterable[WatchlistRecord]]


@dataclass(frozen=True)
class OfficialSource:
    slug: str
    name: str
    publisher: str
    category: str
    url: str
    # Página pública para citar la fuente y revisar el registro a mano.
    info_url: str
    license: str
    parser: Parser
    refresh_every: timedelta = timedelta(hours=24)
    # Encabezados extra para la descarga (el Banco Mundial pide una llave pública).
    headers: tuple[tuple[str, str], ...] = ()


# --- XML ------------------------------------------------------------------------------------------


def _strip_ns(root: ET.Element) -> ET.Element:
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def _xml(data: bytes) -> ET.Element:
    try:
        return _strip_ns(ET.fromstring(data))
    except ET.ParseError as ex:
        raise ValueError(f"El archivo no es un XML válido: {ex}") from None


def _text(el: ET.Element | None, path: str) -> str | None:
    if el is None:
        return None
    found = el.findtext(path)
    return " ".join(found.split()) if found and found.strip() else None


def _join(*parts: str | None) -> str:
    return " ".join(p.strip() for p in parts if p and p.strip())


def _texts(el: ET.Element, path: str) -> list[str]:
    return [" ".join(x.text.split()) for x in el.findall(path) if x.text and x.text.strip()]


# Tipos de "identificación" de OFAC que no son documentos.
_OFAC_NOT_IDS = re.compile(r"website|email|gender|phone|digital currency|vessel|aircraft|organization|secondary|"
                           r"additional sanctions|executive order|effective date|listing date|subject to",
                           re.IGNORECASE)


def parse_ofac(data: bytes, source: str) -> Iterator[WatchlistRecord]:
    """Formato clásico de OFAC (sdn.xml y consolidated.xml): <sdnEntry> con nombre, alias, fechas e identificaciones."""
    root = _xml(data)
    entries = root.findall(".//sdnEntry")
    if not entries:
        raise ValueError("No se encontraron registros <sdnEntry> en el archivo de OFAC.")
    for e in entries:
        uid = _text(e, "uid")
        kind = {"individual": EntryKind.PERSON, "entity": EntryKind.ORGANIZATION, "vessel": EntryKind.VESSEL}.get(
            (_text(e, "sdnType") or "").lower(), EntryKind.OTHER)
        name = _join(_text(e, "firstName"), _text(e, "lastName"))
        if not uid or not name:
            continue
        aliases = [
            _join(_text(a, "firstName"), _text(a, "lastName")) for a in e.findall("./akaList/aka")
            if (_text(a, "category") or "strong").lower() == "strong"
        ]
        ids = [
            _text(i, "idNumber") for i in e.findall("./idList/id")
            if _text(i, "idNumber") and not _OFAC_NOT_IDS.search(_text(i, "idType") or "")
        ]
        yield WatchlistRecord(
            source=source, external_id=uid, kind=kind, name=name, aliases=[a for a in aliases if a],
            birth_dates=_texts(e, "./dateOfBirthList/dateOfBirthItem/dateOfBirth"),
            nationalities=_texts(e, "./nationalityList/nationality/country") + _texts(e, "./citizenshipList/citizenship/country"),
            identifiers=[i for i in ids if i], programs=_texts(e, "./programList/program"),
            url=f"https://sanctionssearch.ofac.treas.gov/Details.aspx?id={uid}", notes=_text(e, "remarks"),
        )


def parse_un(data: bytes, source: str) -> Iterator[WatchlistRecord]:
    """Lista consolidada del Consejo de Seguridad de la ONU (consolidated.xml)."""
    root = _xml(data)
    individuals, entities = root.findall(".//INDIVIDUAL"), root.findall(".//ENTITY")
    if not individuals and not entities:
        raise ValueError("No se encontraron registros INDIVIDUAL ni ENTITY en la lista de la ONU.")
    for node, kind, alias_tag in [(n, EntryKind.PERSON, "INDIVIDUAL_ALIAS") for n in individuals] + \
                                 [(n, EntryKind.ORGANIZATION, "ENTITY_ALIAS") for n in entities]:
        name = _join(*(_text(node, t) for t in ("FIRST_NAME", "SECOND_NAME", "THIRD_NAME", "FOURTH_NAME")))
        data_id = _text(node, "DATAID") or _text(node, "REFERENCE_NUMBER")
        if not name or not data_id:
            continue
        aliases = []
        for a in node.findall(alias_tag):
            # Los alias de calidad baja ("Low") generan muchos falsos positivos.
            if (_text(a, "QUALITY") or "").lower() == "low":
                continue
            aliases += [x.strip() for x in (_text(a, "ALIAS_NAME") or "").split(";") if x.strip()]
        dates = [_text(d, "DATE") or _text(d, "YEAR") for d in node.findall("INDIVIDUAL_DATE_OF_BIRTH")]
        yield WatchlistRecord(
            source=source, external_id=data_id, kind=kind, name=name, aliases=aliases,
            birth_dates=[d for d in dates if d], nationalities=_texts(node, "NATIONALITY/VALUE"),
            identifiers=[x for x in (_text(d, "NUMBER") for d in node.findall("INDIVIDUAL_DOCUMENT")) if x],
            programs=[x for x in [_text(node, "UN_LIST_TYPE"), _text(node, "REFERENCE_NUMBER")] if x],
            listed_on=_text(node, "LISTED_ON"), notes=_text(node, "COMMENTS1"),
            url="https://main.un.org/securitycouncil/es/content/un-sc-consolidated-list",
        )


def parse_eu(data: bytes, source: str) -> Iterator[WatchlistRecord]:
    """Lista consolidada de sanciones financieras de la UE (xmlFullSanctionsList_1_1)."""
    root = _xml(data)
    entries = root.findall(".//sanctionEntity")
    if not entries:
        raise ValueError("No se encontraron registros <sanctionEntity> en la lista de la UE.")
    for e in entries:
        code = ((e.find("subjectType").get("code") if e.find("subjectType") is not None else "") or "").lower()
        kind = {"person": EntryKind.PERSON, "enterprise": EntryKind.ORGANIZATION}.get(code, EntryKind.OTHER)
        names = []
        for n in e.findall("nameAlias"):
            whole = n.get("wholeName") or _join(n.get("firstName"), n.get("middleName"), n.get("lastName"))
            if whole and (n.get("strong", "true").lower() == "true" or not names):
                names.append(" ".join(whole.split()))
        logical_id = e.get("logicalId") or e.get("euReferenceNumber")
        if not names or not logical_id:
            continue
        dates = [b.get("birthdate") or b.get("year") for b in e.findall("birthdate")]
        yield WatchlistRecord(
            source=source, external_id=logical_id, kind=kind, name=names[0], aliases=names[1:],
            birth_dates=[d for d in dates if d],
            nationalities=[c.get("countryIso2Code") or c.get("countryDescription") for c in e.findall("citizenship")
                           if c.get("countryIso2Code") or c.get("countryDescription")],
            identifiers=[i.get("number") or i.get("latinNumber") for i in e.findall("identification")
                         if i.get("number") or i.get("latinNumber")],
            programs=sorted({r.get("programme") for r in e.findall("regulation") if r.get("programme")}),
            listed_on=e.get("designationDate"), notes=_text(e, "remark"),
            url="https://data.europa.eu/data/datasets/consolidated-list-of-persons-groups-and-entities-subject-to-eu-financial-sanctions",
        )


def parse_uk(data: bytes, source: str) -> Iterator[WatchlistRecord]:
    """UK Sanctions List de la FCDO (UK-Sanctions-List.xml), la lista única del Reino Unido desde enero de 2026."""
    root = _xml(data)
    designations = root.findall(".//Designation")
    if not designations:
        raise ValueError("No se encontraron registros <Designation> en la lista del Reino Unido.")
    for d in designations:
        uid = _text(d, "UniqueID")
        kind = {"individual": EntryKind.PERSON, "entity": EntryKind.ORGANIZATION, "ship": EntryKind.VESSEL}.get(
            (_text(d, "IndividualEntityShip") or "").lower(), EntryKind.OTHER)
        primary, aliases = None, []
        for n in d.findall("./Names/Name"):
            full = _text(n, "Name") or _join(*(_text(n, f"Name{i}") for i in range(1, 7)))
            if not full:
                continue
            if primary is None and "primary" in (_text(n, "NameType") or "").lower():
                primary = full
            else:
                aliases.append(full)
        primary = primary or (aliases.pop(0) if aliases else None)
        if not uid or not primary:
            continue
        yield WatchlistRecord(
            source=source, external_id=uid, kind=kind, name=primary, aliases=aliases,
            birth_dates=_texts(d, ".//IndividualDetails//DOB"), nationalities=_texts(d, ".//Nationalities/Nationality"),
            programs=_texts(d, ".//RegimeName"), listed_on=_text(d, "DateDesignated"),
            notes=_text(d, "OtherInformation"),
            url="https://www.gov.uk/government/publications/the-uk-sanctions-list",
        )


# --- CSV ------------------------------------------------------------------------------------------


def decode_text(data: bytes) -> str:
    """Los archivos del SAT y los que salen de Excel suelen venir en Windows-1252, no en UTF-8. Excel también guarda
    "texto Unicode" en UTF-16."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    if data[1:2] == b"\x00" and data[:4].count(b"\x00") >= 2:
        return data.decode("utf-16-le")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _header_key(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_fold(value)).split())


def _rows_after_header(text: str, required: Callable[[list[str]], bool]) -> tuple[list[str], Iterator[list[str]]]:
    """Algunos CSV traen líneas de título antes del encabezado: se busca la primera fila que lo parezca."""
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    for row in reader:
        keys = [_header_key(c) for c in row]
        if required(keys):
            return keys, reader
    raise ValueError("No se encontró la fila de encabezados del archivo.")


def _col(keys: list[str], *options: str, exact: bool = False) -> int | None:
    for opt in options:
        for i, k in enumerate(keys):
            if (k == opt) if exact else (k == opt or k.startswith(opt + " ") or f" {opt}" in f" {k}"):
                return i
    return None


def _cell(row: list[str], i: int | None) -> str:
    return " ".join(row[i].split()) if i is not None and i < len(row) and row[i] else ""


# Situaciones del 69-B que ya no son lista negra: el contribuyente desvirtuó la presunción o ganó en tribunales.
SAT_CLEARED = ("desvirtuado", "sentencia favorable")


def parse_sat_69b(data: bytes, source: str) -> Iterator[WatchlistRecord]:
    """Listado completo del artículo 69-B del CFF (EFOS): presuntos y definitivos. Se omiten los desvirtuados."""
    keys, rows = _rows_after_header(decode_text(data), lambda k: "rfc" in k and any("nombre" in x for x in k))
    rfc, name = _col(keys, "rfc", exact=True), _col(keys, "nombre del contribuyente", "nombre")
    status = _col(keys, "situacion del contribuyente", "situacion")
    for row in rows:
        r, n, s = _cell(row, rfc).upper(), _cell(row, name), _cell(row, status)
        if not r or not n or any(c in ascii_fold(s) for c in SAT_CLEARED):
            continue
        yield WatchlistRecord(
            source=source, external_id=r, kind=EntryKind.ORGANIZATION if len(r) == 12 else EntryKind.PERSON,
            name=n, identifiers=[r], status=s or None, programs=["CFF art. 69-B"],
            url="http://omawww.sat.gob.mx/cifras_sat/Paginas/datos/vinculo.html?page=ListCompleta69B.html",
        )


def parse_worldbank(data: bytes, source: str) -> Iterator[WatchlistRecord]:
    """Empresas e individuos inhabilitados por el Banco Mundial (API de su página de debarred firms)."""
    try:
        payload = json.loads(data)
        rows = payload["response"]["ZPROCSUPP"]
    except (ValueError, KeyError, TypeError):
        raise ValueError("Formato inesperado en la respuesta del Banco Mundial.") from None
    for row in rows:
        name = " ".join(str(row.get("SUPP_NAME") or "").split())
        sid = str(row.get("SUPP_ID") or name)
        if not name:
            continue
        aliases = [a.strip() for a in re.split(r";|\ba\.?k\.?a\.?\b|\bf\.?k\.?a\.?\b", str(row.get("ADD_SUPP_INFO") or ""),
                                                flags=re.IGNORECASE) if len(a.strip()) > 3]
        yield WatchlistRecord(
            source=source, external_id=sid, kind=EntryKind.OTHER, name=name, aliases=aliases,
            nationalities=[row["COUNTRY_NAME"]] if row.get("COUNTRY_NAME") else [],
            programs=[x for x in [row.get("DEBAR_REASON")] if x],
            listed_on=row.get("DEBAR_FROM_DATE"), status=f"Hasta {row['DEBAR_TO_DATE']}" if row.get("DEBAR_TO_DATE") else None,
            url="https://www.worldbank.org/en/projects-operations/procurement/debarred-firms",
        )


# Encabezados que acepta una lista propia. Se comparan sin acentos ni mayúsculas.
CUSTOM_COLUMNS = {
    "name": ("nombre completo", "nombre", "name", "razon social", "denominacion"),
    "given": ("nombres", "nombre s"),
    "last1": ("apellido paterno", "primer apellido", "paterno"),
    "last2": ("apellido materno", "segundo apellido", "materno"),
    "kind": ("tipo de persona", "tipo persona", "tipo", "type"),
    "aliases": ("alias", "aliases", "aka"),
    "birth": ("fecha de nacimiento", "nacimiento", "birth date", "date of birth", "dob"),
    "nationality": ("nacionalidad", "nationality", "pais", "country"),
    "rfc": ("rfc",),
    "curp": ("curp",),
    "id": ("id", "id num", "folio", "clave", "identificador"),
    "list": ("list", "lista"),
    "position": ("cargo", "puesto", "position"),
    "agency": ("dependencia", "institucion", "entidad", "organismo", "department"),
    "reason": ("motivo", "programa", "program", "observaciones", "notas"),
    "location": ("location", "ubicacion", "estado", "municipio"),
    "listed_on": ("publication date", "fecha de publicacion", "fecha de alta"),
    "status": ("status", "estatus", "situacion"),
    "url": ("url", "enlace", "liga", "fuente"),
}
# Columnas que traen algunos archivos exportados de búsquedas y que no describen a la persona.
_IGNORED_SUFFIX = " similarity"


def _custom_rows(data: bytes) -> tuple[list[str], Iterable[list[str]]]:
    """Encabezados y filas de un CSV o de un JSON (lista de objetos, {"results": [...]} o un objeto por línea)."""
    text = decode_text(data).strip()
    if text[:1] in "[{":
        try:
            payload = json.loads(text)
        except ValueError:
            payload = [json.loads(line) for line in text.splitlines() if line.strip()]
        if isinstance(payload, dict):
            payload = next((v for v in payload.values() if isinstance(v, list)), [payload])
        items = [x for x in payload if isinstance(x, dict)]
        if not items:
            raise ValueError("El JSON no trae una lista de registros.")
        names = list(dict.fromkeys(k for item in items for k in item))

        def value(v) -> str:
            if v is None:
                return ""
            if isinstance(v, list):
                return "; ".join(value(x) for x in v if x is not None)
            if isinstance(v, dict):
                return "; ".join(value(x) for x in v.values() if x is not None)
            return str(v)

        return [_header_key(n) for n in names], ([value(item.get(n)) for n in names] for item in items)
    is_header = lambda k: any(x.startswith(("nombre", "name", "razon social")) for x in k)  # noqa: E731
    lines = [line for line in text.splitlines() if line.strip()]
    if any(line.count("|") >= 3 for line in lines[:50]):
        # Separado por "|". Si trae encabezado se usa; si no, las columnas van en el orden fijo del archivo PEP.
        # Las líneas sin "|" (títulos, notas al final) se ignoran.
        # Algunas exportaciones cierran cada línea con una coma de más ("...|MX|0,").
        rows = csv.reader((line.rstrip().removesuffix(",") for line in lines if line.count("|") >= 3), delimiter="|",
                          quoting=csv.QUOTE_NONE)
        first = next(rows)
        keys = [_header_key(c) for c in first]
        if is_header(keys):
            return keys, rows
        return list(PIPE_LAYOUT), itertools.chain([first], rows)
    return _rows_after_header(text, is_header)


# El archivo PEP marca el estatus con 1 (activo) o 0 (inactivo: ya no ocupa el cargo, pesa la mitad en el índice).
STATUS_CODES = {"1": "Activo", "0": "Inactivo"}

# Orden de las columnas en los archivos PEP sin encabezado separados por "|" (los mismos campos de referencia del
# archivo PEP: name, position, department, rfc, birth_date, nationality, status).
PIPE_LAYOUT = ("nombre", "cargo", "dependencia", "rfc", "fecha de nacimiento", "nacionalidad", "status")


def parse_custom_csv(data: bytes, source: str) -> Iterator[WatchlistRecord]:
    """Lista propia (PEP, lista de la UIF para sujetos obligados, sancionados de la SESNA, etc.) en CSV o JSON.

    Necesita una columna de nombre ("nombre"/"name", o "nombre(s)" + "apellido paterno" + "apellido materno"); las
    demás son opcionales: tipo, alias (separados por ;), fecha de nacimiento, nacionalidad, RFC, CURP, id, lista,
    cargo, dependencia, motivo o programa, ubicación, fecha de publicación, estatus y URL.
    """
    keys, rows = _custom_rows(data)
    keys = ["" if k.endswith(_IGNORED_SUFFIX) else k for k in keys]
    cols = {field: _col(keys, *options, exact=True) for field, options in CUSTOM_COLUMNS.items()}
    # Encabezados más largos, como "Nombre del servidor público" o "Fecha de nacimiento (dd/mm/aaaa)".
    for field in ("name", "birth", "nationality", "position", "agency"):
        if cols[field] is None and not (field == "name" and cols["given"] is not None):
            cols[field] = _col(keys, *CUSTOM_COLUMNS[field])
    if cols["name"] is None and cols["given"] is None:
        raise ValueError("No se encontró la columna con el nombre (nombre, name o nombre(s) + apellidos).")
    seen: set[str] = set()
    for number, row in enumerate(rows, start=1):
        get = lambda f: _cell(row, cols[f])  # noqa: E731
        name = get("name") or _join(get("given"), get("last1"), get("last2"))
        if not name:
            continue
        rfc, curp = get("rfc").upper(), get("curp").upper()
        kind_text = ascii_fold(get("kind"))
        if any(w in kind_text for w in ("moral", "empresa", "entidad", "organizacion", "company", "entity")) or len(rfc) == 12:
            kind = EntryKind.ORGANIZATION
        elif any(w in kind_text for w in ("fisica", "persona", "individuo", "person")) or curp or len(rfc) == 13:
            kind = EntryKind.PERSON
        else:
            kind = EntryKind.OTHER
        position = _join(get("position"), f"({get('agency')})" if get("agency") else None)
        # Sin id, RFC ni CURP, la misma persona aparece una vez por cada cargo: el cargo entra en la llave para que
        # no dependa del orden de las filas y la lista del día siguiente conserve las mismas llaves.
        external = get("id") or curp or rfc or f"{ascii_fold(name)}|{get('birth')}" + (
            f"|{hashlib.sha1(ascii_fold(position).encode()).hexdigest()[:12]}" if position else "")
        if external in seen:
            external = f"{external}#{number}"
        seen.add(external)
        yield WatchlistRecord(
            source=source, external_id=external[:200], kind=kind, name=name,
            aliases=[a.strip() for a in re.split(r"[;|]", get("aliases")) if a.strip() and a.strip() != name],
            birth_dates=[get("birth")] if get("birth") else [],
            nationalities=[get("nationality")] if get("nationality") else [],
            identifiers=[x for x in (rfc, curp) if x],
            programs=[x for x in (get("list"), position, get("reason")) if x],
            listed_on=get("listed_on") or None, status=STATUS_CODES.get(get("status"), get("status")) or None,
            url=get("url") or None,
            notes=get("location") or None,
        )


# --- Catálogo -------------------------------------------------------------------------------------

OFFICIAL_SOURCES: dict[str, OfficialSource] = {s.slug: s for s in [
    OfficialSource(
        "ofac-sdn", "OFAC: Specially Designated Nationals (SDN)", "Departamento del Tesoro de EE. UU.",
        Category.SANCTIONS, "https://www.treasury.gov/ofac/downloads/sdn.xml",
        "https://sanctionssearch.ofac.treas.gov/", "Dominio público (gobierno de EE. UU.).", parse_ofac,
        timedelta(hours=6),
    ),
    OfficialSource(
        "ofac-cons", "OFAC: lista consolidada (no SDN)", "Departamento del Tesoro de EE. UU.",
        Category.SANCTIONS, "https://www.treasury.gov/ofac/downloads/consolidated/consolidated.xml",
        "https://ofac.treasury.gov/consolidated-sanctions-list-non-sdn-lists", "Dominio público (gobierno de EE. UU.).",
        parse_ofac, timedelta(hours=6),
    ),
    OfficialSource(
        "un-sc", "ONU: lista consolidada del Consejo de Seguridad", "Consejo de Seguridad de las Naciones Unidas",
        Category.SANCTIONS, "https://scsanctions.un.org/resources/xml/en/consolidated.xml",
        "https://main.un.org/securitycouncil/es/content/un-sc-consolidated-list",
        "Información pública de la ONU; citar la fuente.", parse_un,
    ),
    OfficialSource(
        "eu-fsf", "UE: sanciones financieras consolidadas", "Comisión Europea",
        Category.SANCTIONS,
        "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw",
        "https://data.europa.eu/data/datasets/consolidated-list-of-persons-groups-and-entities-subject-to-eu-financial-sanctions",
        "Reutilización permitida citando la fuente (Decisión 2011/833/UE).", parse_eu,
    ),
    OfficialSource(
        "uk-fcdo", "Reino Unido: UK Sanctions List", "Foreign, Commonwealth & Development Office",
        Category.SANCTIONS, "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.xml",
        "https://www.gov.uk/government/publications/the-uk-sanctions-list",
        "Open Government Licence v3.0; citar la fuente.", parse_uk,
    ),
    OfficialSource(
        "sat-69b", "SAT: artículo 69-B (EFOS presuntos y definitivos)", "Servicio de Administración Tributaria",
        Category.TAX, "http://omawww.sat.gob.mx/cifras_sat/Documents/Listado_Completo_69-B.csv",
        "http://omawww.sat.gob.mx/cifras_sat/Paginas/datos/vinculo.html?page=ListCompleta69B.html",
        "Información pública del SAT (art. 69-B del CFF).", parse_sat_69b,
    ),
    OfficialSource(
        "worldbank", "Banco Mundial: empresas e individuos inhabilitados", "Grupo Banco Mundial",
        Category.DEBARMENT, "https://apigwproxy.worldbank.org/sanctionsList/v1/sanctionsList",
        "https://www.worldbank.org/en/projects-operations/procurement/debarred-firms",
        "Información pública del Banco Mundial; citar la fuente.", parse_worldbank,
        # Solo se descarga si se configura MINOS_WATCHLISTS__WORLDBANK_API_KEY.
        headers=(("apikey", "{worldbank_api_key}"),),
    ),
]}
