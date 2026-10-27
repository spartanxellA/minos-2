"""Coincidencia de nombres contra listas: tolerante con acentos y errores, estricta con homónimos parciales."""
from minos.domain.screening import (
    EntryKind, ScreeningIndex, Strength, Subject, WatchlistRecord, compare, country_code, name_score, normalize_date,
    phonetic,
)
from minos.domain.targets import TargetKind


def rec(name, kind=EntryKind.PERSON, **kw):
    return WatchlistRecord(source="ofac-sdn", external_id=kw.pop("id", name), kind=kind, name=name, **kw)


def person(*names, **kw):
    return Subject(TargetKind.PERSON, list(names), **kw)


def test_accents_order_and_case_do_not_matter():
    assert name_score("José Pérez García", "PEREZ GARCIA, Jose") == 100
    assert name_score("Ñúñez Peña", "nunez pena") == 100


def test_small_misspellings_still_match():
    assert name_score("Joaquín Guzmán Loera", "Joaquin Guzman Lohera") >= 90
    assert name_score("Rafael Caro Quintero", "Rafael Karo Kintero") >= 90
    assert phonetic("gonzalez") == phonetic("gonsales")
    assert phonetic("vazquez") == phonetic("basquez")


def test_missing_second_surname_is_a_possible_match():
    s = name_score("Juan Pérez García", "Juan Perez")
    assert 80 <= s < 100


def test_different_people_do_not_match():
    assert name_score("Juan Pérez García", "Juan Gómez García") == 0
    assert name_score("Juan", "Juan Pérez") == 0  # una sola palabra no basta para una persona
    assert name_score("María de la Luz", "María del Carmen") == 0


def test_companies_ignore_legal_forms():
    assert name_score("Comercializadora Delta, S.A. de C.V.", "COMERCIALIZADORA DELTA SA DE CV", True) == 100
    assert name_score("Comercializadora Delta", "Constructora Delta", True) < 80


def test_birth_date_and_nationality_refine_the_score():
    r = rec("Juan Perez Garcia", birth_dates=["1970-05-03"], nationalities=["Mexico"])
    strong = compare(person("Juan Pérez García", birth_date="03/05/1970", nationality="México"), r)
    assert strong.strength == Strength.STRONG and strong.score == 100
    assert any("Fecha de nacimiento igual" in x for x in strong.reasons)
    assert compare(person("Juan Pérez García", birth_date="1985-01-01"), r) is None  # 100 − 25 < 80
    plain = compare(person("Juan Pérez García"), r)
    assert plain.strength == Strength.POSSIBLE and plain.score == 100


def test_same_identifier_is_a_strong_match_even_with_another_name():
    r = rec("EMPRESA FANTASMA SA DE CV", EntryKind.ORGANIZATION, identifiers=["EFA-010101-AB1"])
    m = compare(Subject(TargetKind.COMPANY, ["Otra Razón Social"], identifiers=["EFA010101AB1"]), r)
    assert m.strength == Strength.STRONG and m.score == 100


def test_different_rfc_rules_out_a_namesake():
    r = rec("Servicios Delta SA de CV", EntryKind.ORGANIZATION, identifiers=["SDE010101AB1"])
    assert compare(Subject(TargetKind.COMPANY, ["Servicios Delta"], identifiers=["SDE990101XY9"]), r) is None


def test_kinds_must_be_compatible():
    assert compare(Subject(TargetKind.COMPANY, ["Juan Perez Garcia"]), rec("Juan Perez Garcia")) is None
    assert compare(person("Ever Given"), rec("Ever Given", EntryKind.VESSEL)) is None
    assert compare(Subject(TargetKind.COUNTRY, ["Iran"]), rec("Iran", EntryKind.OTHER)) is None


def test_non_latin_aliases_are_ignored():
    r = rec("Ivan Petrov", aliases=["Иван Петров"])
    assert compare(person("Иван Петров"), r) is None


def test_index_finds_candidates_by_any_word_and_by_identifier():
    records = [rec("Juan Perez Garcia", id="1"), rec("Pedro Lopez", id="2"),
               rec("Comercial Beta SA", EntryKind.ORGANIZATION, id="3", identifiers=["CBE010101AA1"])]
    index = ScreeningIndex(records)
    assert [m.record.external_id for m in index.screen(person("Juan Pérez"))] == ["1"]
    assert [m.record.external_id for m in index.screen(person("Juan Péres García"))] == ["1"]
    assert index.screen(person("María López")) == []
    found = index.screen(Subject(TargetKind.COMPANY, ["Nombre Distinto"], identifiers=["CBE-010101-AA1"]))
    assert [m.record.external_id for m in found] == ["3"]


def test_dates_and_countries_are_normalized():
    assert normalize_date("1970-5-3") == "1970-05-03"
    assert normalize_date("03/05/1970") == "1970-05-03"
    assert normalize_date("03 May 1970") == "1970-05-03"
    assert normalize_date("circa 1965") == "1965"
    assert normalize_date("desconocida") is None
    assert country_code("México") == country_code("MX") == country_code("Mexico") == "mx"
