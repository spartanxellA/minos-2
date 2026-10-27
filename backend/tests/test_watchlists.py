"""Listas negras: lectores de cada formato, descarga y carga, revisión de objetivos, decisiones y efecto en el riesgo."""
import asyncio
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from minos import db
from minos.bus import MemoryBus
from minos.config import RiskEngineSettings, WatchlistSettings
from minos.domain.risk import SANCTIONS_FLOOR, WatchlistHit, watchlist_adjust
from minos.domain.screening import EntryKind
from minos.main import create_app
from minos.pipeline import RiskEngine
from minos.watchlists import Screener, WatchlistSync
from minos.watchlists.sources import (
    OFFICIAL_SOURCES, parse_custom_csv, parse_eu, parse_ofac, parse_sat_69b, parse_uk, parse_un, parse_worldbank,
)
from test_auth import ADMIN, PASSWORD, app, login, settings  # noqa: F401  (fixtures)

OFAC_XML = b"""<?xml version="1.0" standalone="yes"?>
<sdnList xmlns="https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/XML">
  <publshInformation><Publish_Date>10/24/2026</Publish_Date></publshInformation>
  <sdnEntry>
    <uid>9001</uid><firstName>Juan</firstName><lastName>PEREZ GARCIA</lastName><sdnType>Individual</sdnType>
    <programList><program>SDNTK</program></programList>
    <idList>
      <id><uid>1</uid><idType>R.F.C.</idType><idNumber>PEGJ700503AB1</idNumber></id>
      <id><uid>2</uid><idType>Gender</idType><idNumber>Male</idNumber></id>
    </idList>
    <akaList>
      <aka><uid>3</uid><type>a.k.a.</type><category>strong</category><lastName>EL JUANCHO</lastName></aka>
      <aka><uid>4</uid><type>a.k.a.</type><category>weak</category><lastName>JUANITO</lastName></aka>
    </akaList>
    <dateOfBirthList><dateOfBirthItem><uid>5</uid><dateOfBirth>03 May 1970</dateOfBirth></dateOfBirthItem></dateOfBirthList>
    <nationalityList><nationality><uid>6</uid><country>Mexico</country></nationality></nationalityList>
  </sdnEntry>
  <sdnEntry>
    <uid>9002</uid><lastName>TRANSPORTES ILICITOS S.A. DE C.V.</lastName><sdnType>Entity</sdnType>
    <programList><program>SDNTK</program></programList>
  </sdnEntry>
</sdnList>"""

UN_XML = b"""<CONSOLIDATED_LIST><INDIVIDUALS><INDIVIDUAL>
  <DATAID>6908</DATAID><FIRST_NAME>AHMED</FIRST_NAME><SECOND_NAME>ALI</SECOND_NAME><UN_LIST_TYPE>Al-Qaida</UN_LIST_TYPE>
  <REFERENCE_NUMBER>QDi.001</REFERENCE_NUMBER><LISTED_ON>2001-01-25</LISTED_ON>
  <NATIONALITY><VALUE>Somalia</VALUE></NATIONALITY>
  <INDIVIDUAL_ALIAS><QUALITY>Good</QUALITY><ALIAS_NAME>Ahmad Aly; Ahmed Aly</ALIAS_NAME></INDIVIDUAL_ALIAS>
  <INDIVIDUAL_ALIAS><QUALITY>Low</QUALITY><ALIAS_NAME>Abu</ALIAS_NAME></INDIVIDUAL_ALIAS>
  <INDIVIDUAL_DATE_OF_BIRTH><YEAR>1965</YEAR></INDIVIDUAL_DATE_OF_BIRTH>
</INDIVIDUAL></INDIVIDUALS><ENTITIES><ENTITY>
  <DATAID>7001</DATAID><FIRST_NAME>AL-RASHID TRUST</FIRST_NAME><UN_LIST_TYPE>Al-Qaida</UN_LIST_TYPE>
  <ENTITY_ALIAS><QUALITY>a.k.a.</QUALITY><ALIAS_NAME>Al Rasheed Trust</ALIAS_NAME></ENTITY_ALIAS>
</ENTITY></ENTITIES></CONSOLIDATED_LIST>"""

EU_XML = b"""<export xmlns="http://eu.europa.ec/fpi/fsd/export">
  <sanctionEntity logicalId="13" euReferenceNumber="EU.27.28" designationDate="2022-02-28">
    <regulation programme="RUS"/>
    <subjectType code="person"/>
    <nameAlias wholeName="Ivan Ivanovich Petrov" strong="true"/>
    <nameAlias wholeName="&#1048;&#1074;&#1072;&#1085; &#1055;&#1077;&#1090;&#1088;&#1086;&#1074;" strong="true"/>
    <nameAlias wholeName="Vanya" strong="false"/>
    <citizenship countryIso2Code="RU"/>
    <birthdate birthdate="1960-02-01"/>
    <identification number="123456789"/>
  </sanctionEntity>
  <sanctionEntity logicalId="14"><subjectType code="enterprise"/><nameAlias wholeName="Gazprom Example JSC"/></sanctionEntity>
</export>"""

UK_XML = b"""<Designations><Designation>
  <UniqueID>RUS0001</UniqueID><IndividualEntityShip>Individual</IndividualEntityShip><RegimeName>Russia</RegimeName>
  <DateDesignated>15/03/2022</DateDesignated>
  <Names>
    <Name><Name1>Ivan</Name1><Name6>PETROV</Name6><NameType>Primary Name</NameType></Name>
    <Name><Name1>Ioann</Name1><Name6>PETROFF</Name6><NameType>Alias</NameType></Name>
  </Names>
  <IndividualDetails><Individual><DOBs><DOB>01/02/1960</DOB></DOBs>
    <Nationalities><Nationality>Russia</Nationality></Nationalities></Individual></IndividualDetails>
</Designation></Designations>"""

SAT_CSV = (
    "Información actualizada al 20 de octubre de 2026\n"
    "No,RFC,Nombre del Contribuyente,Situación del contribuyente\n"
    "1,AAA010101AB1,EMPRESA FANTASMA S.A. DE C.V.,Definitivo\n"
    "2,BBB020202CD2,OTRA EMPRESA S.C.,Presunto\n"
    "3,CCC030303EF3,EMPRESA LIMPIA SA,Desvirtuado\n"
    "4,PEGJ700503AB1,JUAN PEREZ GARCIA,Sentencia Favorable\n"
).encode("cp1252")

PEP_CSV = (
    "Nombre(s),Apellido paterno,Apellido materno,Cargo,Dependencia,Fecha de nacimiento,CURP\n"
    "Ana,López,Ruiz,Secretaria de Finanzas,Gobierno del Estado,1975-08-09,LORA750809MDFPZN01\n"
    "Pedro,Gómez,,Diputado local,Congreso,,\n"
).encode()


def test_ofac_reader():
    juan, company = list(parse_ofac(OFAC_XML, "ofac-sdn"))
    assert (juan.external_id, juan.kind, juan.name) == ("9001", EntryKind.PERSON, "Juan PEREZ GARCIA")
    assert juan.aliases == ["EL JUANCHO"]  # los alias débiles no se usan
    assert juan.identifiers == ["PEGJ700503AB1"] and juan.birth_dates == ["03 May 1970"]
    assert juan.nationalities == ["Mexico"] and juan.programs == ["SDNTK"] and "9001" in juan.url
    assert company.kind == EntryKind.ORGANIZATION


def test_un_eu_uk_readers():
    person, entity = list(parse_un(UN_XML, "un-sc"))
    assert person.name == "AHMED ALI" and person.aliases == ["Ahmad Aly", "Ahmed Aly"] and person.birth_dates == ["1965"]
    assert entity.kind == EntryKind.ORGANIZATION and entity.aliases == ["Al Rasheed Trust"]

    petrov, company = list(parse_eu(EU_XML, "eu-fsf"))
    assert petrov.name == "Ivan Ivanovich Petrov" and petrov.aliases == ["Иван Петров"]
    assert petrov.nationalities == ["RU"] and petrov.identifiers == ["123456789"] and petrov.programs == ["RUS"]
    assert company.kind == EntryKind.ORGANIZATION

    [uk] = list(parse_uk(UK_XML, "uk-fcdo"))
    assert uk.name == "Ivan PETROV" and uk.aliases == ["Ioann PETROFF"] and uk.birth_dates == ["01/02/1960"]


def test_sat_reader_skips_cleared_taxpayers():
    rows = list(parse_sat_69b(SAT_CSV, "sat-69b"))
    assert [(r.external_id, r.status, r.kind) for r in rows] == [
        ("AAA010101AB1", "Definitivo", EntryKind.ORGANIZATION), ("BBB020202CD2", "Presunto", EntryKind.ORGANIZATION),
    ]


def test_worldbank_reader():
    data = b'{"response":{"ZPROCSUPP":[{"SUPP_ID":"1","SUPP_NAME":"ACME CONSTRUCTORA","COUNTRY_NAME":"Mexico",' \
           b'"DEBAR_FROM_DATE":"2024-01-01","DEBAR_TO_DATE":"2027-01-01","DEBAR_REASON":"Fraudulent Practice"}]}}'
    [r] = list(parse_worldbank(data, "worldbank"))
    assert r.name == "ACME CONSTRUCTORA" and r.programs == ["Fraudulent Practice"]
    with pytest.raises(ValueError):
        list(parse_worldbank(b"{}", "worldbank"))


def test_custom_csv_reader_joins_name_parts():
    ana, pedro = list(parse_custom_csv(PEP_CSV, "propia-pep"))
    assert ana.name == "Ana López Ruiz" and ana.kind == EntryKind.PERSON
    assert ana.identifiers == ["LORA750809MDFPZN01"] and ana.birth_dates == ["1975-08-09"]
    assert ana.programs == ["Secretaria de Finanzas (Gobierno del Estado)"]
    assert pedro.name == "Pedro Gómez" and pedro.external_id != ana.external_id
    with pytest.raises(ValueError):
        list(parse_custom_csv(b"a,b\n1,2\n", "x"))


def test_watchlist_adjust():
    assert watchlist_adjust(20, []) == 20
    assert watchlist_adjust(20, [WatchlistHit("sanctions")]) == SANCTIONS_FLOOR
    assert watchlist_adjust(90, [WatchlistHit("sanctions")]) == 100
    assert watchlist_adjust(20, [WatchlistHit("tax", "Definitivo")]) == 40
    assert watchlist_adjust(20, [WatchlistHit("tax", "Presunto")]) == 30
    assert watchlist_adjust(20, [WatchlistHit("pep"), WatchlistHit("pep")]) == 30  # la mayor por tipo, no la suma
    assert watchlist_adjust(20, [WatchlistHit("pep"), WatchlistHit("tax")]) == 50
    assert watchlist_adjust(20, [WatchlistHit("pep", "Inactivo")]) == 25  # ya no ocupa el cargo
    assert watchlist_adjust(20, [WatchlistHit("pep", "Activo")]) == 30


@pytest.fixture
def database(tmp_path):
    database = db.Database(f"sqlite+aiosqlite:///{tmp_path / 'minos.db'}")
    asyncio.run(database.create_schema())
    return database


def run(coro):
    return asyncio.run(coro)


def test_sync_downloads_once_and_applies_changes(database):
    calls = []
    files = {"sdn.xml": OFAC_XML}

    def handler(request: httpx.Request):
        calls.append(request.url.path)
        return httpx.Response(200, content=files["sdn.xml"])

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            sync = WatchlistSync(database, MemoryBus(), http, WatchlistSettings(sources=["ofac-sdn"]))
            source = OFFICIAL_SOURCES["ofac-sdn"]
            await sync.refresh(source)
            await sync.refresh(source)  # mismo archivo: no se vuelve a procesar
            files["sdn.xml"] = OFAC_XML.replace(b"<uid>9002</uid>", b"<uid>9003</uid>")
            await sync.refresh(source)
            files["sdn.xml"] = b"<html>mantenimiento</html>"
            await sync.refresh(source)
        async with database.session() as s:
            row = await s.get(db.WatchlistSource, "ofac-sdn")
            ids = sorted((await s.scalars(select(db.WatchlistEntry.external_id))).all())
        return row, ids

    row, ids = run(scenario())
    assert len(calls) == 4
    assert ids == ["9001", "9003"]  # 9002 salió de la lista; la descarga mala no borró nada
    assert row.entry_count == 2 and "sdnEntry" in row.last_error


def test_worldbank_needs_its_key():
    sync = WatchlistSync(None, None, None, WatchlistSettings())
    assert "worldbank" not in [s.slug for s in sync.sources]
    assert "worldbank" in [s.slug for s in WatchlistSync(None, None, None, WatchlistSettings(worldbank_api_key="k")).sources]


async def _seed(database, kind="Person", **target):
    from minos.watchlists.sync import save_list

    await save_list(database, "ofac-sdn", list(parse_ofac(OFAC_XML, "ofac-sdn")), "v1", datetime.now(UTC),
                    official=OFFICIAL_SOURCES["ofac-sdn"])
    t = db.Target(name=target.pop("name", "Juan Pérez García"), kind=kind, aliases=[], keywords=[], excluded_terms=[],
                  handles={}, identifiers={}, **target)
    async with database.session() as s:
        s.add(t)
        await s.commit()
    return t


def test_screener_finds_reopens_and_retires_matches(database):
    async def scenario():
        bus = MemoryBus()
        target = await _seed(database, birth_date="1970-05-03")
        screener = Screener(database, bus, WatchlistSettings())
        assert await screener.cycle() == 1
        assert await screener.cycle() == 0  # nada cambió
        async with database.session() as s:
            [m] = (await s.scalars(select(db.ScreeningMatch))).all()
            alerts = (await s.scalars(select(db.AlertRecord))).all()
        assert (m.status, m.strength, m.external_id, m.category) == ("pending", "strong", "9001", "sanctions")
        assert any("Fecha de nacimiento igual" in r for r in m.reasons)
        assert [a.kind for a in alerts] == ["WatchlistMatch"]

        # Descartada: no vuelve a avisar mientras el registro no cambie.
        async with database.session() as s:
            row = await s.get(db.ScreeningMatch, m.id)
            row.status = "dismissed"
            t = await s.get(db.Target, target.id)
            t.aliases = ["Juanito"]
            await s.commit()
        await screener.cycle()
        async with database.session() as s:
            assert (await s.get(db.ScreeningMatch, m.id)).status == "dismissed"

        # El registro cambia en la lista: la coincidencia descartada se reabre.
        from minos.watchlists.sync import save_list
        changed = OFAC_XML.replace(b"<program>SDNTK</program>", b"<program>SDNTK</program><program>ILLICIT-DRUGS</program>", 1)
        await save_list(database, "ofac-sdn", list(parse_ofac(changed, "ofac-sdn")), "v2", datetime.now(UTC),
                        official=OFFICIAL_SOURCES["ofac-sdn"])
        await screener.cycle()
        async with database.session() as s:
            again = await s.get(db.ScreeningMatch, m.id)
            assert again.status == "pending" and "Reabierta" in again.review_note

        # El objetivo cambia de nombre: la coincidencia deja de estar vigente.
        async with database.session() as s:
            t = await s.get(db.Target, target.id)
            t.name, t.aliases = "María Fernández", []
            await s.commit()
        await screener.cycle()
        async with database.session() as s:
            assert (await s.get(db.ScreeningMatch, m.id)).active is False

    run(scenario())


def test_countries_are_not_screened(database):
    async def scenario():
        await _seed(database, kind="Country", name="Juan Perez Garcia")
        await Screener(database, MemoryBus(), WatchlistSettings()).cycle()
        async with database.session() as s:
            return (await s.scalars(select(db.ScreeningMatch))).all()

    assert run(scenario()) == []


def test_confirmed_match_raises_the_index(database):
    async def scenario():
        target = await _seed(database)
        engine = RiskEngine(database, MemoryBus(), RiskEngineSettings())
        before = await engine.recompute(target.id)
        await Screener(database, MemoryBus(), WatchlistSettings(), risk_engine=engine).cycle()
        async with database.session() as s:
            m = (await s.scalars(select(db.ScreeningMatch))).one()
            m.status = "confirmed"
            await s.commit()
        return before, await engine.recompute(target.id)

    before, after = run(scenario())
    assert before.index == 0 and before.watchlist_impact == 0
    assert after.index == SANCTIONS_FLOOR and after.level == "High" and after.watchlist_impact == SANCTIONS_FLOOR


def test_review_api_roles_audit_and_custom_lists(app):
    with TestClient(app()) as admin, TestClient(app()) as viewer:
        login(admin, *ADMIN)
        admin.post("/api/users", json={"email": "lector@minos.mx", "role": "viewer", "password": PASSWORD})
        login(viewer, "lector@minos.mx", PASSWORD)

        target = admin.post("/api/targets", json={
            "name": "Ana López Ruiz", "kind": "Person", "birthDate": "1975-08-09", "nationality": "México",
            "identifiers": {"curp": " lora750809mdfpzn01 "},
        }).json()
        assert target["identifiers"] == {"curp": "LORA750809MDFPZN01"} and target["birthDate"] == "1975-08-09"
        assert admin.post("/api/targets", json={"name": "X", "birthDate": "09/08/1975"}).status_code == 422
        assert admin.get(f"/api/targets/{target['id']}/screening").json()["status"] == "not_screened"

        # Solo un administrador sube listas propias.
        body = {"name": "PEP estatales", "category": "pep", "csv": PEP_CSV.decode()}
        assert viewer.post("/api/watchlists/custom", json=body).status_code == 403
        r = admin.post("/api/watchlists/custom", json=body)
        assert r.status_code == 201 and r.json()["entries"] == 2
        lists = {w["slug"]: w for w in admin.get("/api/watchlists").json()}
        assert lists["propia-pep-estatales"]["entryCount"] == 2 and lists["propia-pep-estatales"]["category"] == "pep"
        assert lists["ofac-sdn"]["license"] and lists["worldbank"]["configured"] is False

        runtime = admin.app.state.runtime

        admin.portal.call(runtime.screener.cycle)
        screening = admin.get(f"/api/targets/{target['id']}/screening").json()
        assert screening["status"] == "possible" and screening["disclaimer"]
        [match] = screening["matches"]
        assert match["strength"] == "strong" and match["categoryLabel"] == "Persona políticamente expuesta"
        assert [m["id"] for m in admin.get("/api/screening/matches").json()] == [match["id"]]

        url = f"/api/screening/matches/{match['id']}/review"
        assert viewer.post(url, json={"decision": "confirmed", "note": "es ella"}).status_code == 403
        assert admin.post(url, json={"decision": "confirmed"}).status_code == 422  # sin nota
        reviewed = admin.post(url, json={"decision": "confirmed", "note": "Misma CURP"}).json()
        assert reviewed["status"] == "confirmed" and reviewed["reviewedByEmail"] == ADMIN[0]
        risk = admin.get(f"/api/targets/{target['id']}/risk/latest").json()
        assert risk["watchlistImpact"] == 10

        events = admin.get("/api/audit", params={"action": "screening."}).json()["events"]
        assert events[0]["changes"] == {"status": ["pending", "confirmed"]} and events[0]["detail"]["note"] == "Misma CURP"
        assert admin.get("/api/audit", params={"action": "watchlist."}).json()["events"][0]["action"] == "watchlist.uploaded"

        # Borrar la lista retira la coincidencia y el índice vuelve a la normalidad.
        assert admin.delete("/api/watchlists/custom/propia-pep-estatales").status_code == 204
        assert admin.get(f"/api/targets/{target['id']}/risk/latest").json()["watchlistImpact"] == 0
        assert admin.get(f"/api/targets/{target['id']}/screening").json()["status"] == "clear"


def test_custom_json_with_the_pep_export_fields():
    data = b"""[
      {"alias": ["Pepe Gomez"], "alias_similarity": 0.91, "birth_date": "1968-04-12", "department": "Senado",
       "id_num": "PEP-1", "list": "PEP Nacional", "location": null, "name": "Jose Gomez Hernandez",
       "name_similarity": 1.0, "nationality": "Mexico", "position": "Senador", "program": null,
       "publication_date": null, "rfc": "GOHJ680412AB1", "status": "Activo"},
      {"alias": null, "birth_date": null, "department": "Congreso", "id_num": "PEP-2", "list": "PEP Estatal",
       "name": "Laura Diaz", "nationality": null, "position": "Diputada", "rfc": null, "status": "Inactivo"}
    ]"""
    jose, laura = list(parse_custom_csv(data, "propia-pep"))
    assert (jose.external_id, jose.name, jose.kind) == ("PEP-1", "Jose Gomez Hernandez", EntryKind.PERSON)
    assert jose.aliases == ["Pepe Gomez"] and jose.identifiers == ["GOHJ680412AB1"] and jose.birth_dates == ["1968-04-12"]
    assert jose.programs == ["PEP Nacional", "Senador (Senado)"] and jose.status == "Activo"
    assert laura.aliases == [] and laura.status == "Inactivo" and laura.nationalities == []
    # El mismo archivo en CSV.
    csv_data = ("alias,alias_similarity,birth_date,department,id_num,list,location,name,name_similarity,nationality,"
                "position,program,publication_date,rfc,status\n"
                "Pepe Gomez,0.91,1968-04-12,Senado,PEP-1,PEP Nacional,,Jose Gomez Hernandez,1,Mexico,Senador,,,"
                "GOHJ680412AB1,Activo\n").encode()
    [same] = list(parse_custom_csv(csv_data, "propia-pep"))
    assert same == jose


def test_custom_pipe_file_without_header():
    data = ("ALFONSO TORRES JIMENEZ|DIRECCION DE PLANEACION|COMISION NACIONAL DE BUSQUEDA DE PERSONAS|||MX|0\n"
            "MARÍA \"LA JEFA\" PÉREZ|DIRECTORA GENERAL|SECRETARÍA DE ECONOMÍA|||MX|1\n\n").encode("cp1252")
    alfonso, maria = list(parse_custom_csv(data, "propia-pep"))
    assert alfonso.name == "ALFONSO TORRES JIMENEZ" and alfonso.nationalities == ["MX"]
    assert alfonso.programs == ["DIRECCION DE PLANEACION (COMISION NACIONAL DE BUSQUEDA DE PERSONAS)"]
    assert maria.name == 'MARÍA "LA JEFA" PÉREZ'  # las comillas no rompen la fila
    assert (alfonso.status, alfonso.identifiers, alfonso.birth_dates) == ("0", [], [])
    [full] = list(parse_custom_csv(b"LUIS RUIZ|SENADOR|SENADO|RUIL700101AB1|1970-01-01|MX|1\n", "x"))
    assert (full.identifiers, full.birth_dates, full.status) == (["RUIL700101AB1"], ["1970-01-01"], "1")
    # Con encabezado y "|" también funciona por nombre de columna.
    [r] = list(parse_custom_csv(b"name|position|nationality\nAna Ruiz|Senadora|MX\n", "x"))
    assert (r.name, r.programs, r.nationalities) == ("Ana Ruiz", ["Senadora"], ["MX"])


def test_pep_upload_of_the_pipe_file_screens_people(app):
    with TestClient(app()) as admin:
        login(admin, *ADMIN)
        target = admin.post("/api/targets", json={"name": "Alfonso Torres Jiménez", "kind": "Person"}).json()
        company = admin.post("/api/targets", json={"name": "Alfonso Torres Jimenez", "kind": "Company"}).json()
        csv = "ALFONSO TORRES JIMENEZ|DIRECCION DE PLANEACION|COMISION NACIONAL DE BUSQUEDA DE PERSONAS|||MX|0\n"
        r = admin.post("/api/watchlists/custom", json={"name": "PEP", "category": "pep", "csv": csv})
        assert r.status_code == 201 and r.json()["entries"] == 1
        admin.portal.call(admin.app.state.runtime.screener.cycle)
        [m] = admin.get(f"/api/targets/{target['id']}/screening").json()["matches"]
        assert m["entry"]["kind"] == "person" and m["entry"]["nationalities"] == ["MX"]
        assert admin.get(f"/api/targets/{company['id']}/screening").json()["matches"] == []
