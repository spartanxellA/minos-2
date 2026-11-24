"""Lo que se escribe en .env debe llegar a los contenedores: cada ajuste de Settings tiene que estar en docker-compose.yml."""
import re
from pathlib import Path

import pytest
from pydantic import BaseModel

from minos.config import Settings

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"
# La imagen fija dónde están los cuestionarios; crear tablas sin migraciones es solo para pruebas.
NOT_IN_DOCKER = {"MINOS_SURVEYS_PATH", "MINOS_CREATE_SCHEMA"}


def env_names(model: type[BaseModel], prefix: str = "MINOS_") -> set[str]:
    names: set[str] = set()
    for name, field in model.model_fields.items():
        if isinstance(field.annotation, type) and issubclass(field.annotation, BaseModel):
            names |= env_names(field.annotation, f"{prefix}{name.upper()}__")
        else:
            names.add(f"{prefix}{name.upper()}")
    return names


def test_every_setting_reaches_docker():
    passed = set(re.findall(r"^\s+(MINOS_[A-Z0-9_]+):", COMPOSE.read_text(), re.MULTILINE))
    assert env_names(Settings) - NOT_IN_DOCKER - passed == set()


def test_values_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MINOS_AUTH__MAX_FAILED_LOGINS", "8")
    monkeypatch.setenv("MINOS_RISK_ENGINE__MEDIA_WEIGHT", "0.7")
    monkeypatch.setenv("MINOS_TIMEZONE", "America/Monterrey")
    monkeypatch.setenv("MINOS_INGESTION__GEO__DEFAULT_COUNTRY", "CO")
    s = Settings(_env_file=None)
    assert (s.auth.max_failed_logins, s.risk_engine.media_weight, s.timezone, s.ingestion.geo.default_country) == (
        8, 0.7, "America/Monterrey", "CO")


def test_empty_value_means_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MINOS_AUTH__MAX_FAILED_LOGINS", "")
    monkeypatch.setenv("MINOS_TIMEZONE", "")
    s = Settings(_env_file=None)
    assert s.auth.max_failed_logins == 5 and s.timezone == "America/Mexico_City"
