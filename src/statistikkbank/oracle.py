from __future__ import annotations

import logging
import math
import re
from typing import Any

import oracledb
import pandas as pd

from statistikkbank.config import DATABASE_PROFILES, DatabaseConnection, SmallAggregate, validate_identifier

LOGGER = logging.getLogger(__name__)


def validate_select(sql: str) -> str:
    mask = list(sql)
    semicolons: list[int] = []
    index = 0
    while index < len(sql):
        if sql.startswith("--", index):
            end = sql.find("\n", index)
            end = len(sql) if end == -1 else end
            mask[index:end] = " " * (end - index)
            index = end
        elif sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            if end == -1:
                raise ValueError("SQL-filen inneholder en kommentar som ikke er avsluttet.")
            end += 2
            mask[index:end] = " " * (end - index)
            index = end
        elif sql[index] in {"'", '"'}:
            quote = sql[index]
            start = index
            index += 1
            while index < len(sql):
                if sql[index] == quote:
                    if index + 1 < len(sql) and sql[index + 1] == quote:
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            else:
                raise ValueError("SQL-filen inneholder en streng eller identifikator som ikke er avsluttet.")
            mask[start:index] = " " * (index - start)
        elif (
            sql[index] == ":"
            and index + 1 < len(sql)
            and re.match(r"[A-Za-z_0-9]", sql[index + 1])
        ):
            raise ValueError("SQL-spørringen kan ikke inneholde bind-parametere.")
        elif sql[index] == ";":
            semicolons.append(index)
            index += 1
        else:
            index += 1
    cleaned = "".join(mask).strip()
    if not re.match(r"(?is)^(select|with)\b", cleaned):
        raise ValueError("SQL-filen må inneholde én SELECT-spørring.")
    if re.match(r"(?is)^with\b", cleaned) and not re.search(r"\bselect\b", cleaned, re.I):
        raise ValueError("SQL-filen må inneholde én SELECT-spørring.")
    if re.search(r"\bfor\s+update\b", cleaned, re.I):
        raise ValueError("SQL-spørringen kan ikke låse rader med FOR UPDATE.")
    if len(semicolons) > 1 or (
        semicolons and "".join(mask[semicolons[0] + 1 :]).strip()
    ):
        raise ValueError("SQL-filen må inneholde nøyaktig én SELECT-spørring.")
    if re.search(r"\b(insert|update|delete|merge|create|alter|drop|begin|declare)\b", cleaned, re.I):
        raise ValueError("SQL-filen må inneholde bare én SELECT-spørring.")
    return sql[: semicolons[0]].rstrip() if semicolons else sql.strip()


def connect(configuration: DatabaseConnection) -> oracledb.Connection:
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
        cursor.execute(
            f"ALTER SESSION SET CURRENT_SCHEMA = {configuration.schema_name}"
        )
    return connection


def read_query(connection: oracledb.Connection, sql: str, aggregate: SmallAggregate) -> tuple[pd.DataFrame, dict[str, str]]:
    query = validate_select(sql)
    with connection.cursor() as cursor:
        cursor.execute(query)
        columns = [description[0].lower() for description in cursor.description or []]
        rows = cursor.fetchall()
        source_types = {
            description[0].lower(): oracle_type(description)
            for description in cursor.description or []
        }
    frame = pd.DataFrame(rows, columns=columns)
    expected = [item.kolonne for item in aggregate.variabler] + [
        aggregate.tallkolonne.kolonne
    ]
    if len(columns) != len(set(columns)) or set(columns) != {item.lower() for item in expected}:
        raise ValueError(
            f"Kolonnene fra SQL-spørringen for {aggregate.tabell} må være "
            f"{', '.join(expected)}."
        )
    frame = frame.rename(
        columns={column: column.lower() for column in frame.columns}
    )
    frame = frame[[item.lower() for item in expected]]
    return frame, source_types


def oracle_type(description: tuple[Any, ...]) -> str:
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
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name, data_type, data_length, data_precision, data_scale "
            "FROM dba_columns WHERE owner = :owner AND table_name = :table_name",
            owner=schema.upper(),
            table_name=table.upper(),
        )
        return {
            name.lower(): (data_type.upper(), length, precision, scale)
            for name, data_type, length, precision, scale in cursor.fetchall()
        }


def table_exists(connection: oracledb.Connection, schema: str, table: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM dba_tables WHERE owner = :owner AND table_name = :table_name",
            owner=schema.upper(),
            table_name=table.upper(),
        )
        return cursor.fetchone() is not None


def ensure_schema(
    connection: oracledb.Connection,
    schema: str,
    aggregate: SmallAggregate,
    frame: pd.DataFrame,
    source_types: dict[str, str],
    *,
    migrate: bool,
    dry_run: bool = False,
) -> None:
    if frame.empty:
        LOGGER.info("Ingen rader for %s; databaseskjemaet endres ikke.", aggregate.tabell)
        return
    table = validate_identifier(aggregate.tabell, "tabell")
    owner = validate_identifier(schema, "schema")
    expected = {str(column).lower(): source_types.get(str(column).lower(), pandas_type(frame[column])) for column in frame.columns}
    expected["prikket"] = "NUMBER(1)"
    if not table_exists(connection, owner, table):
        if not migrate:
            raise ValueError(f"Tabellen {owner}.{table} finnes ikke. Kjør kommandoen med migrer.")
        if dry_run:
            LOGGER.info("Ville opprettet tabellen %s.%s.", owner, table)
            return
        definitions = ", ".join(
            f"{validate_identifier(name, 'kolonne')} {data_type}"
            for name, data_type in expected.items()
        )
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE TABLE {owner}.{table} ({definitions})")
        return

    actual = table_columns(connection, owner, table)
    missing = set(expected) - set(actual)
    unexpected = set(actual) - set(expected)
    incompatible = {
        name for name in set(expected) & set(actual)
        if not compatible_type(expected[name], actual[name])
    }
    if unexpected or incompatible:
        details = []
        if unexpected:
            details.append(f"ukjente kolonner: {', '.join(sorted(unexpected))}")
        if incompatible:
            details.append(f"ulike datatyper: {', '.join(sorted(incompatible))}")
        raise ValueError(f"Skjemaet for {owner}.{table} avviker ({'; '.join(details)}).")
    if missing and not migrate:
        raise ValueError(
            f"Tabellen {owner}.{table} mangler kolonner: {', '.join(sorted(missing))}. "
            "Kjør kommandoen med migrer."
        )
    if missing:
        if dry_run:
            LOGGER.info("Ville lagt til kolonnene %s i %s.%s.", ", ".join(sorted(missing)), owner, table)
            return
        with connection.cursor() as cursor:
            for name in sorted(missing):
                cursor.execute(
                    f"ALTER TABLE {owner}.{table} ADD "
                    f"({validate_identifier(name, 'kolonne')} {expected[name]})"
                )


def pandas_type(series: pd.Series) -> str:
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
    actual_type, actual_length, actual_precision, actual_scale = actual
    def family(value: str) -> str:
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
        expected_length = int(re.search(r"\((\d+)\)", expected).group(1)) if "(" in expected else 4000
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


def write_result(
    connection: oracledb.Connection,
    schema: str,
    aggregate: SmallAggregate,
    frame: pd.DataFrame,
    source_types: dict[str, str],
    *,
    migrate: bool,
    dry_run: bool = False,
) -> None:
    if frame.empty:
        LOGGER.info("Ingen rader for %s; databasen endres ikke.", aggregate.tabell)
        return
    ensure_schema(
        connection, schema, aggregate, frame, source_types, migrate=migrate, dry_run=dry_run
    )
    if dry_run:
        LOGGER.info("Ville skrevet %d rader til %s.%s.", len(frame), schema, aggregate.tabell)
        return
    table = f"{validate_identifier(schema, 'schema')}.{validate_identifier(aggregate.tabell, 'tabell')}"
    columns = list(frame.columns)
    period = aggregate.periodisering.lower()
    if period not in frame.columns:
        raise ValueError(f"Periodekolonnen {aggregate.periodisering} mangler i resultatet.")
    try:
        with connection.cursor() as cursor:
            if aggregate.inkrementell == "overskriv_alt":
                cursor.execute(f"DELETE FROM {table}")
                to_insert = frame
            elif aggregate.inkrementell == "overskriv_siste_periode":
                latest = frame[period].max()
                cursor.execute(
                    f"DELETE FROM {table} WHERE {period} = :period", period=latest
                )
                to_insert = frame[frame[period] == latest]
            else:
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
                to_insert = frame[~frame[period].isin(existing)]
            if not to_insert.empty:
                names = ", ".join(validate_identifier(name, "kolonne") for name in columns)
                binds = ", ".join(f":{index + 1}" for index in range(len(columns)))
                cursor.executemany(
                    f"INSERT INTO {table} ({names}) VALUES ({binds})",
                    [tuple(_db_value(value) for value in row) for row in to_insert.itertuples(index=False, name=None)],
                )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def _db_value(value: Any) -> Any:
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


def read_metadata(connection: oracledb.Connection, schema: str, aggregate: SmallAggregate) -> dict[str, str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT comments FROM dba_tab_comments WHERE owner = :owner "
            "AND table_name = :table_name",
            owner=schema.upper(),
            table_name=aggregate.tabell.upper(),
        )
        row = cursor.fetchone()
        result = parse_metadata(row[0] if row else None)
        entities = [(aggregate.tabell, aggregate)] + [
            (variable.kolonne, variable)
            for variable in [*aggregate.variabler, aggregate.tallkolonne]
        ]
        for column, model in entities:
            if column == aggregate.tabell:
                comments = result
            else:
                cursor.execute(
                    "SELECT comments FROM dba_col_comments WHERE owner = :owner "
                    "AND table_name = :table_name AND column_name = :column_name",
                    owner=schema.upper(),
                    table_name=aggregate.tabell.upper(),
                    column_name=column.upper(),
                )
                row = cursor.fetchone()
                comments = parse_metadata(row[0] if row else None)
            for tag in ("navn", "navn_en", "beskrivelse", "beskrivelse_en"):
                value = getattr(model, tag)
                if value:
                    LOGGER.info("%s.%s hentes fra konfigurasjonen.", column, tag)
                elif comments.get(tag.upper()):
                    setattr(model, tag, comments[tag.upper()])
                    LOGGER.info("%s.%s hentes fra databasekommentar.", column, tag)
                else:
                    raise ValueError(
                        f"Metadatafeltet {tag} mangler for {column}; angi det i YAML "
                        "eller legg det til som databasekommentar."
                    )
                LOGGER.debug("%s.%s = %s", column, tag, getattr(model, tag))
    return result


def parse_metadata(comment: str | None) -> dict[str, str]:
    if not comment:
        return {}
    matches = list(re.finditer(r"#(NAVN(?:_EN)?|BESKRIVELSE(?:_EN)?)\b", comment, re.I))
    values: dict[str, str] = {}
    seen: set[str] = set()
    for index, match in enumerate(matches):
        tag = match.group(1).upper()
        if tag in seen:
            raise ValueError(f"Databasekommentaren inneholder taggen #{tag} flere ganger.")
        seen.add(tag)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(comment)
        value = comment[match.end():end].strip()
        if value:
            values[tag] = value
    return values
