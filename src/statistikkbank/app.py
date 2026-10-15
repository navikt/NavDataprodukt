from __future__ import annotations

import logging
from pathlib import Path

from statistikkbank.config import Configuration, resolve_secret
from statistikkbank import lokal, oracle
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
    aggregates = configuration.smale_aggregater
    if migrate and output_format != "database":
        raise ValueError("Kommandoen migrer krever --output-format=database.")
    if selected_tables:
        wanted = {name.lower() for name in selected_tables}
        aggregates = [item for item in aggregates if item.tabell.lower() in wanted]
        unknown = wanted - {item.tabell.lower() for item in aggregates}
        if unknown:
            raise ValueError(f"Fant ikke småaggregatene: {', '.join(sorted(unknown))}.")

    connection = None
    database_input = input_format == "database"
    database_output = output_format == "database"
    can_skip_connection = dry_run and not database_input
    if database_input or (database_output and not can_skip_connection):
        connection_values = configuration.connection.model_dump()
        connection_values["user"] = resolve_secret(configuration.connection.user)
        connection_values["password"] = resolve_secret(
            configuration.connection.password, password=True
        )
        connection = oracle.connect(configuration.connection.model_copy(update=connection_values))

    try:
        for aggregate in aggregates:
            LOGGER.info("Behandler småaggregatet %s.", aggregate.tabell)
            source_types: dict[str, str] = {}
            if input_format == "csv":
                if input_directory is None:
                    raise ValueError("Du må angi --input-directory når --input-format=csv.")
                input_path = _resolve_directory(input_directory, config_directory)
                data = lokal.read_csv(input_path, aggregate)
            else:
                if connection is None:
                    raise RuntimeError("Databasetilkobling mangler.")
                sql_path = (config_directory / aggregate.sporring_sql).resolve()
                try:
                    sql_text = sql_path.read_text(encoding="utf-8")
                except OSError as exc:
                    raise ValueError(f"SQL-filen kan ikke leses: {sql_path}") from exc
                data, source_types = oracle.read_query(connection, sql_text, aggregate)

            if connection is not None:
                oracle.read_metadata(
                    connection, configuration.connection.schema_name, aggregate
                )
            result = run_mock(data)
            result = result[[*data.columns, "prikket"]]

            if output_format == "csv":
                if output_directory is None:
                    raise ValueError("Du må angi --output-directory når --output-format=csv.")
                lokal.write_csv(
                    result,
                    _resolve_directory(output_directory, config_directory),
                    aggregate,
                    dry_run=dry_run,
                )
            elif migrate:
                if connection is None:
                    if dry_run:
                        LOGGER.info(
                            "Ville kontrollert migrering av %s.%s.",
                            configuration.connection.schema_name,
                            aggregate.tabell,
                        )
                        continue
                    raise RuntimeError("Databasetilkobling mangler.")
                oracle.ensure_schema(
                    connection,
                    configuration.connection.schema_name,
                    aggregate,
                    result,
                    source_types,
                    migrate=True,
                    dry_run=dry_run,
                )
            else:
                if connection is None:
                    if dry_run:
                        LOGGER.info(
                            "Ville skrevet %d rader til %s.%s.",
                            len(result),
                            configuration.connection.schema_name,
                            aggregate.tabell,
                        )
                        continue
                    raise RuntimeError("Databasetilkobling mangler.")
                oracle.write_result(
                    connection,
                    configuration.connection.schema_name,
                    aggregate,
                    result,
                    source_types,
                    migrate=False,
                    dry_run=dry_run,
                )
    finally:
        if connection is not None:
            connection.close()


def _resolve_directory(directory: Path, config_directory: Path) -> Path:
    resolved = directory.expanduser()
    return (config_directory / resolved).resolve() if not resolved.is_absolute() else resolved.resolve()
