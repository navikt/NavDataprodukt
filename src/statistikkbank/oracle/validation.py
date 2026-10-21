from __future__ import annotations

import re
from typing import Any

import oracledb
import pandas as pd

from statistikkbank.config import SmallAggregate, validate_identifier


def validate_result_columns(columns: list[str], aggregate: SmallAggregate) -> list[str]:
    """Kontrollerer SQL-resultatkolonnene mot aggregatkonfigurasjonen."""
    expected = [variable.kolonne for variable in aggregate.variabler] + [
        aggregate.tallkolonne.kolonne
    ]
    normalized_columns = [column.lower() for column in columns]
    if (
        len(normalized_columns) != len(set(normalized_columns))
        or set(normalized_columns) != {column.lower() for column in expected}
    ):
        raise ValueError(
            f"Kolonnene fra SQL-spørringen for {aggregate.tabell} må være "
            f"{', '.join(expected)}."
        )
    return [column.lower() for column in expected]


def oracle_type(description: tuple[Any, ...]) -> str:
    """Oversetter Oracle-markørens kolonnetype til SQL-typeuttrykk."""
    type_name = getattr(description[1], "name", str(description[1])).upper()
    size = description[2]
    precision = description[4]
    scale = description[5]
    if "NUMBER" in type_name:
        return f"NUMBER({precision},{scale or 0})" if precision else "NUMBER"
    if "BINARY_DOUBLE" in type_name:
        return "BINARY_DOUBLE"
    if "BINARY_FLOAT" in type_name:
        return "BINARY_FLOAT"
    if "TIMESTAMP_TZ" in type_name:
        return "TIMESTAMP WITH TIME ZONE"
    if "TIMESTAMP_LTZ" in type_name:
        return "TIMESTAMP WITH LOCAL TIME ZONE"
    if "TIMESTAMP" in type_name:
        return "TIMESTAMP"
    if "DATE" in type_name:
        return "DATE"
    if "CLOB" in type_name:
        return "CLOB"
    if "BLOB" in type_name:
        return "BLOB"
    if "RAW" in type_name:
        if size and size <= 2000:
            return f"RAW({size})"
        return "BLOB"
    if "CHAR" in type_name:
        return f"VARCHAR2({size})" if size and size <= 32767 else "CLOB"
    return "VARCHAR2(4000)"


def table_columns(
    connection: oracledb.Connection, schema: str, table: str
) -> dict[str, tuple[str, int | None, int | None, int | None]]:
    """Henter kolonnenavn og datatypeinformasjon for en Oracle-tabell."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name, data_type, data_length, data_precision, data_scale "
            "FROM sys.dba_tab_columns WHERE owner = :owner AND table_name = :table_name",
            owner=schema.upper(),
            table_name=table.upper(),
        )
        return {
            name.lower(): (data_type.upper(), length, precision, scale)
            for name, data_type, length, precision, scale in cursor.fetchall()
        }


def table_exists(connection: oracledb.Connection, schema: str, table: str) -> bool:
    """Kontrollerer om en Oracle-tabell finnes i angitt skjema."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM sys.dba_tables WHERE owner = :owner AND table_name = :table_name",
            owner=schema.upper(),
            table_name=table.upper(),
        )
        return cursor.fetchone() is not None


def check_schema(
    connection: oracledb.Connection,
    schema: str,
    aggregate: SmallAggregate,
    frame: pd.DataFrame,
    source_types: dict[str, str],
) -> None:
    """Avviser manglende, uventede eller inkompatible tabellkolonner."""
    table = validate_identifier(aggregate.tabell)
    owner = validate_identifier(schema)
    expected = {
        str(column).lower(): source_types.get(
            str(column).lower(), pandas_type(frame[column])
        )
        for column in frame.columns
    }
    expected["prikket"] = "NUMBER(1)"
    if not table_exists(connection, owner, table):
        raise ValueError(
            f"Tabellen {owner}.{table} finnes ikke. Opprett tabellen før kjøring."
        )

    actual = table_columns(connection, owner, table)
    missing = set(expected) - set(actual)
    unexpected = set(actual) - set(expected)
    incompatible = {
        name
        for name in set(expected) & set(actual)
        if not compatible_type(expected[name], actual[name])
    }
    if unexpected or incompatible:
        details = []
        if unexpected:
            details.append(f"ukjente kolonner: {', '.join(sorted(unexpected))}")
        if incompatible:
            details.append(f"ulike datatyper: {', '.join(sorted(incompatible))}")
        raise ValueError(f"Skjemaet for {owner}.{table} avviker ({'; '.join(details)}).")
    if missing:
        raise ValueError(
            f"Tabellen {owner}.{table} mangler kolonner: {', '.join(sorted(missing))}. "
            "Oppdater databaseskjemaet før kjøring."
        )


def pandas_type(series: pd.Series) -> str:
    """Utleder en passende Oracle-type fra en pandas-serie."""
    if pd.api.types.is_bool_dtype(series.dtype):
        return "NUMBER(1)"
    if pd.api.types.is_integer_dtype(series.dtype):
        return "NUMBER(38,0)"
    if pd.api.types.is_float_dtype(series.dtype):
        return "NUMBER"
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        return "TIMESTAMP"
    return "VARCHAR2(4000)"


def compatible_type(
    expected: str, actual: tuple[str, int | None, int | None, int | None]
) -> bool:
    """Kontrollerer om faktisk Oracle-kolonnedefinisjon rommer forventet type."""
    actual_type, actual_length, actual_precision, actual_scale = actual

    def family(value: str) -> str:
        """Mapper SQL-typer til sammenlignbare datatypefamilier."""
        if "NUMBER" in value or "FLOAT" in value or "INTEGER" in value:
            return "NUMBER"
        if "CHAR" in value:
            return "CHAR"
        if "TIMESTAMP" in value:
            return "TIMESTAMP"
        if value == "DATE":
            return "DATE"
        if value == "BLOB":
            return "BLOB"
        if value.startswith("RAW") or value == "LONG RAW":
            return "RAW"
        return value

    expected_family = family(expected)
    if expected_family != family(actual_type):
        return False
    if expected_family == "CHAR":
        expected_length = (
            int(re.search(r"\((\d+)\)", expected).group(1))
            if "(" in expected
            else 4000
        )
        return actual_length is None or actual_length >= expected_length
    if expected_family == "RAW":
        match = re.search(r"\((\d+)\)", expected)
        return (
            actual_length is None
            or match is None
            or actual_length >= int(match.group(1))
        )
    if expected_family == "TIMESTAMP":
        expected_type = expected.replace("(6)", "")
        actual_match = re.search(r"\((\d+)\)", actual_type)
        actual_precision_value = int(actual_match.group(1)) if actual_match else 6
        normalized_actual = re.sub(r"\(\d+\)", "", actual_type).strip()
        normalized_expected = re.sub(r"\(\d+\)", "", expected_type).strip()
        return (
            normalized_expected == normalized_actual
            and actual_precision_value >= 6
        )
    if expected_family == "NUMBER":
        match = re.search(r"\((\d+)(?:,(-?\d+))?\)", expected)
        if match:
            if actual_precision is None:
                return True
            expected_precision = int(match.group(1))
            expected_scale = int(match.group(2) or 0)
            actual_scale = actual_scale or 0
            return (
                actual_precision - actual_scale
                >= expected_precision - expected_scale
                and actual_scale >= expected_scale
            )
        return actual_precision is None
    return True
