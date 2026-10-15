from __future__ import annotations

import logging
from pathlib import Path

import oracledb
import pandas as pd

from statistikkbank import lokal, oracle
from statistikkbank.config import Configuration, SmallAggregate, resolve_secret
from statistikkbank.prikking import prikking as run_mock

LOGGER = logging.getLogger(__name__)


def run(
    configuration: Configuration,
    config_directory: Path,
    *,
    selected_tables: list[str] | None = None,
    input_format: str = "database",
    input_directory: Path | None = None,
    output_format: str = "database",
    output_directory: Path | None = None,
    dry_run: bool = False,
    migrate: bool = False,
) -> None:
    if migrate and output_format != "database":
        raise ValueError("Kommandoen migrer krever --output-format=database.")

    aggregates = _select_aggregates(configuration, selected_tables)
    connection = _connect_if_needed(
        configuration,
        input_format=input_format,
        output_format=output_format,
        dry_run=dry_run,
    )
    try:
        for aggregate in aggregates:
            _process_aggregate(
                configuration,
                aggregate,
                config_directory,
                connection,
                input_format=input_format,
                input_directory=input_directory,
                output_format=output_format,
                output_directory=output_directory,
                dry_run=dry_run,
                migrate=migrate,
            )
    finally:
        if connection is not None:
            connection.close()


def _select_aggregates(
    configuration: Configuration, selected_tables: list[str] | None
) -> list[SmallAggregate]:
    if not selected_tables:
        return configuration.smale_aggregater

    wanted = {name.lower() for name in selected_tables}
    aggregates = [
        aggregate
        for aggregate in configuration.smale_aggregater
        if aggregate.tabell.lower() in wanted
    ]
    unknown = wanted - {aggregate.tabell.lower() for aggregate in aggregates}
    if unknown:
        raise ValueError(f"Fant ikke småaggregatene: {', '.join(sorted(unknown))}.")
    return aggregates


def _connect_if_needed(
    configuration: Configuration,
    *,
    input_format: str,
    output_format: str,
    dry_run: bool,
) -> oracledb.Connection | None:
    database_input = input_format == "database"
    database_output = output_format == "database"
    if not database_input and (not database_output or dry_run):
        return None

    connection = configuration.connection
    resolved_connection = connection.model_copy(
        update={
            "user": resolve_secret(connection.user),
            "password": resolve_secret(connection.password, password=True),
        }
    )
    return oracle.connect(resolved_connection)


def _process_aggregate(
    configuration: Configuration,
    aggregate: SmallAggregate,
    config_directory: Path,
    connection: oracledb.Connection | None,
    *,
    input_format: str,
    input_directory: Path | None,
    output_format: str,
    output_directory: Path | None,
    dry_run: bool,
    migrate: bool,
) -> None:
    LOGGER.info("Behandler småaggregatet %s.", aggregate.tabell)
    data, source_types = _read_input(
        aggregate,
        config_directory,
        connection,
        input_format=input_format,
        input_directory=input_directory,
    )
    if connection is not None:
        oracle.read_metadata(connection, configuration.connection.schema_name, aggregate)

    result = run_mock(data)
    result = result[[*data.columns, "prikket"]]
    _write_output(
        configuration,
        aggregate,
        result,
        source_types,
        connection,
        output_format=output_format,
        output_directory=output_directory,
        config_directory=config_directory,
        dry_run=dry_run,
        migrate=migrate,
    )


def _read_input(
    aggregate: SmallAggregate,
    config_directory: Path,
    connection: oracledb.Connection | None,
    *,
    input_format: str,
    input_directory: Path | None,
) -> tuple[pd.DataFrame, dict[str, str]]:
    if input_format == "csv":
        if input_directory is None:
            raise ValueError("Du må angi --input-directory når --input-format=csv.")
        directory = _resolve_directory(input_directory, config_directory)
        return lokal.read_csv(directory, aggregate), {}

    if connection is None:
        raise RuntimeError("Databasetilkobling mangler.")
    sql_path = (config_directory / aggregate.sporring_sql).resolve()
    try:
        sql_text = sql_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"SQL-filen kan ikke leses: {sql_path}") from exc
    return oracle.read_query(connection, sql_text, aggregate)


def _write_output(
    configuration: Configuration,
    aggregate: SmallAggregate,
    result: pd.DataFrame,
    source_types: dict[str, str],
    connection: oracledb.Connection | None,
    *,
    output_format: str,
    output_directory: Path | None,
    config_directory: Path,
    dry_run: bool,
    migrate: bool,
) -> None:
    if output_format == "csv":
        _write_csv(
            result,
            aggregate,
            output_directory,
            config_directory,
            dry_run=dry_run,
        )
    else:
        _write_database(
            configuration,
            aggregate,
            result,
            source_types,
            connection,
            dry_run=dry_run,
            migrate=migrate,
        )


def _write_csv(
    result: pd.DataFrame,
    aggregate: SmallAggregate,
    output_directory: Path | None,
    config_directory: Path,
    *,
    dry_run: bool,
) -> None:
    if output_directory is None:
        raise ValueError("Du må angi --output-directory når --output-format=csv.")
    directory = _resolve_directory(output_directory, config_directory)
    lokal.write_csv(result, directory, aggregate, dry_run=dry_run)


def _write_database(
    configuration: Configuration,
    aggregate: SmallAggregate,
    result: pd.DataFrame,
    source_types: dict[str, str],
    connection: oracledb.Connection | None,
    *,
    dry_run: bool,
    migrate: bool,
) -> None:
    schema = configuration.connection.schema_name
    if connection is None:
        if not dry_run:
            raise RuntimeError("Databasetilkobling mangler.")
        if migrate:
            LOGGER.info(
                "Ville kontrollert migrering av %s.%s.", schema, aggregate.tabell
            )
        else:
            LOGGER.info(
                "Ville skrevet %d rader til %s.%s.",
                len(result),
                schema,
                aggregate.tabell,
            )
        return

    if migrate:
        oracle.ensure_schema(
            connection,
            schema,
            aggregate,
            result,
            source_types,
            migrate=True,
            dry_run=dry_run,
        )
        return
    oracle.write_result(
        connection,
        schema,
        aggregate,
        result,
        source_types,
        migrate=False,
        dry_run=dry_run,
    )


def _resolve_directory(directory: Path, config_directory: Path) -> Path:
    resolved = directory.expanduser()
    if resolved.is_absolute():
        return resolved.resolve()
    return (config_directory / resolved).resolve()
