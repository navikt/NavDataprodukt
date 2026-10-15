from __future__ import annotations

import logging
from pathlib import Path

import oracledb
import pandas as pd

from statistikkbank import oracle, lokal
from statistikkbank.config import Configuration, SmallAggregate, resolve_secret
from statistikkbank.prikking import prikking

LOGGER = logging.getLogger(__name__)


def run(
    configuration: Configuration,
    config_directory: Path,
    *,
    selected_tables: list[str] | None = None,
    input_directory: Path | None = None,
    output_directory: Path | None = None,
    dry_run: bool = False,
) -> None:
    aggregates = _select_aggregates(configuration, selected_tables)
    connection = _connect_if_needed(
        configuration,
        input_directory=input_directory,
        output_directory=output_directory,
        dry_run=dry_run,
    )
    try:
        for aggregate in aggregates:
            _process_aggregate(
                configuration,
                aggregate,
                config_directory,
                connection,
                input_directory=input_directory,
                output_directory=output_directory,
                dry_run=dry_run,
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
    input_directory: Path | None,
    output_directory: Path | None,
    dry_run: bool,
) -> oracledb.Connection | None:
    database_input = input_directory is None
    database_output = output_directory is None
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
    input_directory: Path | None,
    output_directory: Path | None,
    dry_run: bool,
) -> None:
    LOGGER.info("Behandler småaggregatet %s.", aggregate.tabell)
    data, source_types = _read_input(
        aggregate,
        config_directory,
        connection,
        input_directory=input_directory,
    )
    if connection is not None:
        oracle.read_metadata(connection, configuration.connection.schema_name, aggregate)

    result = prikking(
        data,
        periode=aggregate.periodisering,
        formula=aggregate.formula,
        tallKol=aggregate.tallkolonne.kolonne,
        prikking=aggregate.prikking,
        saerskilt=aggregate.saerskilt,
    )
    result = result[[*data.columns, "prikket"]]
    _write_output(
        configuration,
        aggregate,
        result,
        source_types,
        connection,
        output_directory=output_directory,
        config_directory=config_directory,
        dry_run=dry_run,
    )


def _read_input(
    aggregate: SmallAggregate,
    config_directory: Path,
    connection: oracledb.Connection | None,
    *,
    input_directory: Path | None,
) -> tuple[pd.DataFrame, dict[str, str]]:
    if input_directory is not None:
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
    output_directory: Path | None,
    config_directory: Path,
    dry_run: bool,
) -> None:
    if output_directory is not None:
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
        )


def _write_csv(
    result: pd.DataFrame,
    aggregate: SmallAggregate,
    output_directory: Path,
    config_directory: Path,
    *,
    dry_run: bool,
) -> None:
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
) -> None:
    schema = configuration.connection.schema_name
    if connection is None:
        if not dry_run:
            raise RuntimeError("Databasetilkobling mangler.")
        LOGGER.info(
            "Ville skrevet %d rader til %s.%s.",
            len(result),
            schema,
            aggregate.tabell,
        )
        return

    oracle.write_result(
        connection,
        schema,
        aggregate,
        result,
        source_types,
        dry_run=dry_run,
    )


def _resolve_directory(directory: Path, config_directory: Path) -> Path:
    resolved = directory.expanduser()
    if resolved.is_absolute():
        return resolved.resolve()
    return (config_directory / resolved).resolve()
