from __future__ import annotations

import logging
import math
from typing import Any

import oracledb
import pandas as pd

from statistikkbank.config import (
    DATABASE_PROFILES,
    DatabaseConnection,
    SmallAggregate,
    validate_identifier,
)
from statistikkbank.oracle.validation import check_schema, oracle_type, validate_result_columns

LOGGER = logging.getLogger(__name__)


def connect(configuration: DatabaseConnection) -> oracledb.Connection:
    """Kobler til konfigurert Oracle-database og velger skjema."""
    profile = DATABASE_PROFILES[configuration.database]
    connection = oracledb.connect(
        user=configuration.user,
        password=configuration.password,
        dsn=oracledb.makedsn(
            profile["host"], profile["port"], service_name=profile["service_name"]
        ),
        tcp_connect_timeout=configuration.timeout,
    )
    with connection.cursor() as cursor:
        cursor.execute(f"ALTER SESSION SET CURRENT_SCHEMA = {configuration.schema_name}")
    return connection


def read_query(
    connection: oracledb.Connection, sql: str, aggregate: SmallAggregate
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Kjører aggregatspørringen og returnerer data med kildetyper."""
    with connection.cursor() as cursor:
        cursor.execute(sql.strip().removesuffix(";").rstrip())
        description = cursor.description or []
        columns = [column[0].lower() for column in description]
        rows = cursor.fetchall()
        source_types = {
            column[0].lower(): oracle_type(column) for column in description
        }
    expected_columns = validate_result_columns(columns, aggregate)
    frame = pd.DataFrame(rows, columns=columns)
    return frame[expected_columns], source_types


def write_result(
    connection: oracledb.Connection,
    schema: str,
    aggregate: SmallAggregate,
    frame: pd.DataFrame,
    source_types: dict[str, str],
    *,
    dry_run: bool = False,
) -> None:
    """Validerer skjemaet og skriver aggregatresultatet transaksjonelt."""
    if frame.empty:
        LOGGER.info("Ingen rader for %s; databasen endres ikke.", aggregate.tabell)
        return
    check_schema(connection, schema, aggregate, frame, source_types)
    if dry_run:
        LOGGER.info(
            "Ville skrevet %d rader til %s.%s.",
            len(frame),
            schema,
            aggregate.tabell,
        )
        return
    table = (
        f"{validate_identifier(schema, 'schema')}."
        f"{validate_identifier(aggregate.tabell, 'tabell')}"
    )
    period = aggregate.periodisering.lower()
    if period not in frame.columns:
        raise ValueError(f"Periodekolonnen {aggregate.periodisering} mangler i resultatet.")

    try:
        with connection.cursor() as cursor:
            to_insert = _apply_incremental_mode(
                cursor, table, aggregate, frame, period
            )
            _insert_rows(cursor, table, to_insert)
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def _apply_incremental_mode(
    cursor: Any,
    table: str,
    aggregate: SmallAggregate,
    frame: pd.DataFrame,
    period: str,
) -> pd.DataFrame:
    """Sletter eller filtrerer perioder etter konfigurert inkrementell modus."""
    if aggregate.inkrementell == "overskriv_alt":
        cursor.execute(f"DELETE FROM {table}")
        return frame

    if aggregate.inkrementell == "overskriv_siste_periode":
        latest = frame[period].max()
        cursor.execute(f"DELETE FROM {table} WHERE {period} = :period", period=latest)
        return frame[frame[period] == latest]

    cursor.execute(f"SELECT DISTINCT {period} FROM {table}")
    existing = {row[0] for row in cursor.fetchall()}
    incoming = set(frame[period].dropna().tolist())
    duplicates = incoming & existing
    if duplicates:
        LOGGER.warning(
            "Periodene %s finnes allerede i %s og hoppes over.",
            ", ".join(map(str, sorted(duplicates, key=str))),
            aggregate.tabell,
        )
    return frame[~frame[period].isin(existing)]


def _insert_rows(cursor: Any, table: str, frame: pd.DataFrame) -> None:
    """Setter inn alle datarammerader med parameteriserte verdier."""
    if frame.empty:
        return
    columns = list(frame.columns)
    names = ", ".join(validate_identifier(name, "kolonne") for name in columns)
    binds = ", ".join(f":{index + 1}" for index in range(len(columns)))
    rows = [
        tuple(_db_value(value) for value in row)
        for row in frame.itertuples(index=False, name=None)
    ]
    cursor.executemany(f"INSERT INTO {table} ({names}) VALUES ({binds})", rows)


def _db_value(value: Any) -> Any:
    """Konverterer pandas- og numpy-verdier til Oracle-kompatible verdier."""
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, bool):
        return int(value)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, float) and math.isnan(value):
        return None
    return value
