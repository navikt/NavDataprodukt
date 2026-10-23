from __future__ import annotations

import getpass
import json
import os
import re
import sys
from enum import StrEnum
from pathlib import Path
from typing import Any, Annotated
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator, AfterValidator


class ConfigError(ValueError):
    """Feil i konfigurasjonen av statistikkprodukt."""


DATABASE_PROFILES = {
    "DWHP": {"host": "dwhp.example.nav.no", "port": 1521, "service_name": "DWHP"},
    "DWHQ": {"host": "dwhq.example.nav.no", "port": 1521, "service_name": "DWHQ"},
    "DWHU": {"host": "dwhu.example.nav.no", "port": 1521, "service_name": "DWHU"},
    "DWHR": {"host": "dwhr.example.nav.no", "port": 1521, "service_name": "DWHR"},
}

_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]{0,127}$")



class InkrementalMode(StrEnum):
    OVERSKRIV_IKKE = "overskriv_ikke"
    OVERSKRIV_ALT = "overskriv_alt"
    OVERSKRIV_SISTE_PERIODE = "overskriv_siste_periode"

def validate_identifier(value: str) -> str:
    """Kontrollerer og småbokstaverer en Oracle-identifikator."""
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"Må være et gyldig Oracle-navn, er: {value!r}")
    return value.lower()

def is_not_empty(value: str) -> str:
    """Validerer at en streng ikke er tom eller bare mellomrom."""
    if not value.strip():
        raise ConfigError("Strengen kan ikke være tom eller bare mellomrom.")
    return value


NonEmptyString = Annotated[str, AfterValidator(is_not_empty)]
OracleIdentifier = Annotated[str, AfterValidator(validate_identifier)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Metadata(StrictModel):
    navn: str | None = None
    navn_en: str | None = None
    innhold: str | None = None
    innhold_en: str | None = None


class DatabaseConnection(StrictModel):
    database: str
    schema_name: OracleIdentifier = Field(alias="schema")
    user: NonEmptyString
    password: str
    timeout: int = Field(default=30, gt=0)

    @field_validator("database")
    @classmethod
    def validate_database(cls, value: str) -> str:
        """Kontrollerer at databasenavnet viser til en støttet profil."""
        if value not in DATABASE_PROFILES:
            valid_db_names = ", ".join(sorted(DATABASE_PROFILES.keys()))
            raise ConfigError("database må være en av " + valid_db_names)
        return value

    @field_validator("password")
    @classmethod
    def require_password_reference(cls, value: str) -> str:
        """Krever en støttet hemmelighetsreferanse for passordet."""
        if "://" not in value:
            raise ConfigError("password må være en hemmelighetsreferanse")
        if urlsplit(value).scheme not in {"env", "terminal", "gsm"}:
            raise ConfigError("password må bruke env://, terminal:// eller gsm://")
        return value


class Variable(StrictModel):
    navn: str | None = None
    navn_en: str | None = None
    kolonne: OracleIdentifier
    innhold: str | None = None
    innhold_en: str | None = None

    # For everyone of navn, navn_en, ..., we want to normalize empty strings to None
    @field_validator(*Metadata.model_fields.keys(), mode="before")
    @classmethod
    def normalize_metadata(cls, value: Any) -> Any:
        """Gjør tomme metadatafelt om til manglende verdier."""
        return value.strip() or None if isinstance(value, str) else value


class SmallAggregate(StrictModel):
    navn: str | None = None
    navn_en: str | None = None
    tabell: OracleIdentifier
    innhold: str | None = None
    innhold_en: str | None = None
    sporring_sql: NonEmptyString
    periodisering: OracleIdentifier
    inkrementell: InkrementalMode
    tallkolonne: Variable
    formula: NonEmptyString
    prikking: bool
    saerskilt: bool
    variabler: list[Variable]

    # For everyone of navn, navn_en, ..., we want to normalize empty strings to None
    @field_validator(*Metadata.model_fields.keys(), mode="before")
    @classmethod
    def normalize_metadata(cls, value: Any) -> Any:
        """Gjør tomme metadatafelt om til manglende verdier."""
        return value.strip() or None if isinstance(value, str) else value

    @field_validator("inkrementell", mode="before")
    @classmethod
    def validate_incremental_mode(cls, value: str) -> str:
        """Kontrollerer at inkrementell modus er støttet."""
        allowed = list(InkrementalMode)
        if value not in allowed:
            raise ConfigError(f"inkrementell må være én av {', '.join(sorted(allowed))}")
        return value

    @field_validator("variabler")
    @classmethod
    def validate_variables(cls, value: list[Variable]) -> list[Variable]:
        """Krever minst én dimensjonsvariabel."""
        if not value:
            raise ConfigError("variabler må inneholde minst én variabel")
        return value

    @model_validator(mode="after")
    def validate_column_contract(self) -> SmallAggregate:
        """Kontrollerer at dimensjoner og måltall har unike kolonner."""
        columns = [variable.kolonne for variable in self.variabler]
        if len(columns) != len(set(columns)):
            raise ConfigError("variabler kan ikke inneholde gjentatte kolonner")
        if self.tallkolonne.kolonne in columns:
            raise ConfigError("tallkolonne kan ikke også være en variabel")
        if self.periodisering not in columns:
            raise ConfigError("periodisering må være en av variablene")
        return self


class Configuration(StrictModel):
    connection: DatabaseConnection
    smale_aggregater: list[SmallAggregate]

    @field_validator("smale_aggregater")
    @classmethod
    def validate_aggregates(cls, value: list[SmallAggregate]) -> list[SmallAggregate]:
        """Krever aggregater med unike måltabeller."""
        if not value:
            raise ConfigError("smale_aggregater må inneholde minst ett aggregat")
        tables = [item.tabell.upper() for item in value]
        if len(tables) != len(set(tables)):
            raise ConfigError("tabellnavn må være unike")
        return value


def load_configuration(config_path: str | Path | None) -> tuple[Configuration, Path]:
    """Leser YAML-konfigurasjonen og returnerer modellen og filens mappe."""

    if config_path is None:
        raise ConfigError("Konfigurasjonsfilen må angis med --config eller STATISTIKKPRODUKT_CONFIG.")

    import yaml

    def unique_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
        """Avviser gjentatte nøkler i YAML-mappinger."""
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in mapping:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"nøkkelen {key!r} er oppgitt flere ganger",
                    key_node.start_mark,
                )
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping

    class UniqueSafeLoader(yaml.SafeLoader):
        pass

    UniqueSafeLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping
    )

    path = Path(config_path).expanduser().resolve()
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueSafeLoader)
    except UnicodeDecodeError as exc:
        raise ConfigError("Konfigurasjonsfilen må være kodet som UTF-8.") from exc
    except OSError as exc:
        raise ConfigError(f"Konfigurasjonsfilen kan ikke leses: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError("Konfigurasjonsfilen inneholder ugyldig YAML.") from exc

    try:
        config = Configuration.model_validate(data)
    except Exception as exc:
        from pydantic import ValidationError

        if isinstance(exc, ValidationError):
            raise ConfigError(
                "Konfigurasjonen er ugyldig:\n"
                + "\n".join(format_validation_error(error) for error in exc.errors())
            ) from exc
        raise
    return config, path.parent


def format_validation_error(error: dict[str, Any]) -> str:
    """Gjør en Pydantic-feil om til en kort norsk melding."""
    location = ".".join(str(item) for item in error.get("loc", ())) or "konfigurasjonen"
    if error["type"] == "extra_forbidden":
        return f"Ukjent felt: {location}."
    if error["type"] == "missing":
        return f"Feltet {location} mangler."
    message = str(error.get("msg", ""))
    if message.startswith("Value error, "):
        message = message.removeprefix("Value error, ")
    if not message or not any(character in message for character in "æøåÆØÅ"):
        return f"Ugyldig verdi for feltet {location}."
    return f"{location}: {message}"


def resolve_secret(reference: str, *, password: bool = False) -> str:
    """Slår opp en bokstavelig verdi eller støttet hemmelighetsreferanse."""
    if "://" not in reference:
        if password:
            raise ConfigError("Passord må angis som en hemmelighetsreferanse.")
        return reference

    parsed = urlsplit(reference)
    if parsed.scheme == "env":
        key = parsed.netloc or parsed.path.lstrip("/")
        value = os.environ.get(key)
        if value is None:
            raise ConfigError(f"Miljøvariabelen {key} er ikke satt.")
        return value
    if parsed.scheme == "terminal":
        if not sys.stdin.isatty():
            raise ConfigError("terminal:// kan bare brukes når standard input er en terminal.")
        value = getpass.getpass("Skriv inn hemmelig verdi: ")
        if not value:
            raise ConfigError("Den innleste hemmeligheten kan ikke være tom.")
        return value
    if parsed.scheme == "gsm":
        from google.api_core.exceptions import GoogleAPIError
        from google.auth.exceptions import GoogleAuthError
        from google.cloud import secretmanager

        secret_path = parsed.path.strip("/")
        if parsed.netloc:
            secret_path = f"{parsed.netloc}/{secret_path}"
        parts = secret_path.split("/")
        key = None
        if len(parts) >= 7 and parts[-3] == "versions":
            key = parts.pop()
        secret_name = "/".join(parts)
        try:
            response = secretmanager.SecretManagerServiceClient().access_secret_version(
                request={"name": secret_name}
            )
            payload = response.payload.data.decode("utf-8")
            if key:
                values = json.loads(payload)
                if not isinstance(values, dict) or key not in values:
                    raise ConfigError(f"Nøkkelen {key!r} finnes ikke i den lagrede hemmeligheten.")
                payload = values[key]
            if not isinstance(payload, str) or not payload:
                raise ConfigError("Den refererte hemmelighetsverdien er tom eller ugyldig.")
            return payload
        except (GoogleAPIError, GoogleAuthError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConfigError("Kunne ikke hente den refererte hemmeligheten fra Google Secret Manager.") from exc
    raise ConfigError(f"Ukjent hemmelighetsreferanse: {parsed.scheme}://.")
