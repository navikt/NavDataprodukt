from __future__ import annotations

import getpass
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DATABASE_PROFILES = {
    "DWHP": {"host": "dwhp.example.nav.no", "port": 1521, "service_name": "DWHP"},
    "DWHQ": {"host": "dwhq.example.nav.no", "port": 1521, "service_name": "DWHQ"},
    "DWHU": {"host": "dwhu.example.nav.no", "port": 1521, "service_name": "DWHU"},
    "DWHR": {"host": "dwhr.example.nav.no", "port": 1521, "service_name": "DWHR"},
}

_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]{0,127}$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class DatabaseConnection(StrictModel):
    database: str
    schema_name: str = Field(alias="schema")
    user: str
    password: str
    timeout: int = Field(default=30, gt=0)

    @field_validator("database")
    @classmethod
    def validate_database(cls, value: str) -> str:
        if value not in DATABASE_PROFILES:
            raise ValueError("database må være DWHP, DWHQ, DWHU eller DWHR")
        return value

    @field_validator("schema_name")
    @classmethod
    def validate_schema_name(cls, value: str) -> str:
        return validate_identifier(value, "schema")

    @field_validator("user")
    @classmethod
    def validate_user(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("user kan ikke være tom")
        return value

    @field_validator("password")
    @classmethod
    def require_password_reference(cls, value: str) -> str:
        if "://" not in value:
            raise ValueError("password må være en hemmelighetsreferanse")
        if urlsplit(value).scheme not in {"env", "terminal", "gsm"}:
            raise ValueError("password må bruke env://, terminal:// eller gsm://")
        return value


class Variable(StrictModel):
    navn: str | None = None
    navn_en: str | None = None
    kolonne: str
    beskrivelse: str | None = None
    beskrivelse_en: str | None = None

    @field_validator("navn", "navn_en", "beskrivelse", "beskrivelse_en", mode="before")
    @classmethod
    def normalize_metadata(cls, value: Any) -> Any:
        return value.strip() or None if isinstance(value, str) else value

    @field_validator("kolonne")
    @classmethod
    def validate_column(cls, value: str) -> str:
        return validate_identifier(value, "kolonne")


class SmallAggregate(StrictModel):
    navn: str | None = None
    navn_en: str | None = None
    tabell: str
    beskrivelse: str | None = None
    beskrivelse_en: str | None = None
    sporring_sql: str
    periodisering: str
    inkrementell: str
    tallkolonne: Variable
    formula: str
    prikking: bool
    saerskilt: bool
    variabler: list[Variable]

    @field_validator("navn", "navn_en", "beskrivelse", "beskrivelse_en", mode="before")
    @classmethod
    def normalize_metadata(cls, value: Any) -> Any:
        return value.strip() or None if isinstance(value, str) else value

    @field_validator("tabell", "periodisering")
    @classmethod
    def validate_identifiers(cls, value: str, info: Any) -> str:
        return validate_identifier(value, info.field_name)

    @field_validator("inkrementell")
    @classmethod
    def validate_incremental_mode(cls, value: str) -> str:
        allowed = {"overskriv_ikke", "overskriv_alt", "overskriv_siste_periode"}
        if value not in allowed:
            raise ValueError(f"inkrementell må være en av {', '.join(sorted(allowed))}")
        return value

    @field_validator("sporring_sql")
    @classmethod
    def validate_sql_path(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("sporring_sql kan ikke være tom")
        return value

    @field_validator("formula")
    @classmethod
    def validate_formula(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("formula kan ikke være tom")
        return value

    @field_validator("variabler")
    @classmethod
    def validate_variables(cls, value: list[Variable]) -> list[Variable]:
        if not value:
            raise ValueError("variabler må inneholde minst én variabel")
        return value

    @model_validator(mode="after")
    def validate_column_contract(self) -> SmallAggregate:
        columns = [variable.kolonne for variable in self.variabler]
        if len(columns) != len(set(columns)):
            raise ValueError("variabler kan ikke inneholde gjentatte kolonner")
        if self.tallkolonne.kolonne in columns:
            raise ValueError("tallkolonne kan ikke også være en variabel")
        if self.periodisering not in columns:
            raise ValueError("periodisering må være en av variablene")
        return self


class Configuration(StrictModel):
    connection: DatabaseConnection
    smale_aggregater: list[SmallAggregate]

    @field_validator("smale_aggregater")
    @classmethod
    def validate_aggregates(cls, value: list[SmallAggregate]) -> list[SmallAggregate]:
        if not value:
            raise ValueError("smale_aggregater må inneholde minst ett aggregat")
        tables = [item.tabell.upper() for item in value]
        if len(tables) != len(set(tables)):
            raise ValueError("tabellnavn må være unike")
        return value


def validate_identifier(value: str, field_name: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field_name} må være et gyldig Oracle-navn")
    return value.lower()


def load_configuration(config_path: str | Path) -> tuple[Configuration, Path]:
    try:
        import yaml
    except ImportError as exc:
        raise ValueError("YAML-støtte mangler i installasjonen av statistikkbank.") from exc

    def unique_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
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
        raise ValueError("Konfigurasjonsfilen må være kodet som UTF-8.") from exc
    except OSError as exc:
        raise ValueError(f"Konfigurasjonsfilen kan ikke leses: {path}") from exc
    except yaml.YAMLError as exc:
        raise ValueError("Konfigurasjonsfilen inneholder ugyldig YAML.") from exc
    try:
        config = Configuration.model_validate(data)
    except Exception as exc:
        from pydantic import ValidationError

        if isinstance(exc, ValidationError):
            raise ValueError(
                "Konfigurasjonen er ugyldig:\n"
                + "\n".join(format_validation_error(error) for error in exc.errors())
            ) from exc
        raise
    return config, path.parent


def format_validation_error(error: dict[str, Any]) -> str:
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
    if "://" not in reference:
        if password:
            raise ValueError("Passord må angis som en hemmelighetsreferanse.")
        return reference

    parsed = urlsplit(reference)
    if parsed.scheme == "env":
        key = parsed.netloc or parsed.path.lstrip("/")
        value = os.environ.get(key)
        if value is None:
            raise ValueError(f"Miljøvariabelen {key} er ikke satt.")
        return value
    if parsed.scheme == "terminal":
        if not sys.stdin.isatty():
            raise ValueError("terminal:// kan bare brukes når standard input er en terminal.")
        value = getpass.getpass("Skriv inn hemmelig verdi: ")
        if not value:
            raise ValueError("Den innleste hemmeligheten kan ikke være tom.")
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
                    raise ValueError(f"Nøkkelen {key!r} finnes ikke i den lagrede hemmeligheten.")
                payload = values[key]
            if not isinstance(payload, str) or not payload:
                raise ValueError("Den refererte hemmelighetsverdien er tom eller ugyldig.")
            return payload
        except (GoogleAPIError, GoogleAuthError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Kunne ikke hente den refererte hemmeligheten fra Google Secret Manager.") from exc
    raise ValueError(f"Ukjent hemmelighetsreferanse: {parsed.scheme}://.")
