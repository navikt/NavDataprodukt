from __future__ import annotations

from pathlib import Path

import logging
import oracledb
import pandas as pd
from statistikkprodukt import oracle, lokal
from statistikkprodukt.config import Configuration, InkrementalMode, SmallAggregate, resolve_secret
from statistikkprodukt.prikking import prikking

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
    """Kjører valgte aggregater fra valgt kilde til valgt mål."""
    aggregates = _select_aggregates(configuration, selected_tables)

    if _needs_db_connection(input_directory, output_directory, dry_run):
        connection = _connect(configuration)
    else:
        connection = None

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
        configuration: Configuration,
        selected_tables: list[str] | None
) -> list[SmallAggregate]:
    """Velger alle aggregater eller kontrollerer eksplisitte tabellvalg."""
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


def _needs_db_connection(input_directory: Path | None, output_directory: Path | None, dry_run: bool) -> bool:
    """Sjekker om en databaseforbindelse er nødvendig basert på input/output."""
    database_input = input_directory is None
    database_output = output_directory is None
    return database_input or (database_output and not dry_run)


def _connect(configuration: Configuration) -> oracledb.Connection | None:
    """Oppretter Oracle-tilkobling bare når kilden eller målet trenger den."""
    user = resolve_secret(configuration.connection.user)
    password = resolve_secret(configuration.connection.password, password=True)
    resolved_connection = configuration.connection.model_copy(
        update={
            "user": user,
            "password": password
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
    """Leser, prikker og lagrer ett småaggregat."""
    LOGGER.info("Behandler småaggregatet %s.", aggregate.tabell)
    periods_to_load = _get_periods_to_load(
        configuration,
        aggregate,
        config_directory,
        connection,
        input_directory=input_directory,
        output_directory=output_directory,
        dry_run=dry_run,
    )

    data, source_types = _read_input(
        aggregate,
        config_directory,
        connection,
        input_directory=input_directory,
        periods_to_load=periods_to_load,
    )
    LOGGER.info("Lest %d rader for %s.", len(data), aggregate.tabell)

    if connection is not None:
        LOGGER.info("Henter metadata for %s fra Oracle.", aggregate.tabell)
        table_metadata = oracle.read_metadata(connection, configuration.connection.schema_name, aggregate)

    LOGGER.info("Prikker %d rader for %s.", len(data), aggregate.tabell)
    result = prikking(
        data,
        periode=aggregate.periodisering,
        formula=aggregate.formula,
        tallKol=aggregate.tallkolonne.kolonne,
        prikking=aggregate.prikking,
        saerskilt=aggregate.saerskilt,
    )
    result = result[[*data.columns, "prikket"]]

    LOGGER.info("Skriver %d rader for %s.", len(result), aggregate.tabell)
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


def _get_periods_to_load(
    configuration: Configuration,
    aggregate: SmallAggregate,
    config_directory: Path,
    connection: oracledb.Connection | None,
    *,
    input_directory: Path | None,
    output_directory: Path | None,
    dry_run: bool,
) -> list[int | str] | None:
    """Velger perioder før innlesing; None betyr alle, en tom liste betyr ingen."""
    if output_directory is not None or dry_run:
        return None
    if connection is None:
        raise RuntimeError("Databasetilkobling mangler.")

    available, existing = _fetch_periods(
        configuration,
        aggregate,
        config_directory,
        connection,
        input_directory=input_directory,
    )
    if aggregate.inkrementell == InkrementalMode.OVERSKRIV_ALT:
        return sorted(available)

    missing = available - existing
    if aggregate.inkrementell == InkrementalMode.OVERSKRIV_SISTE_PERIODE:
        max_available = {max(existing)} if existing and max(existing) in available else set()
        return sorted(missing.union(max_available))
    elif aggregate.inkrementell == InkrementalMode.OVERSKRIV_IKKE:
        return sorted(missing)
    else:
        raise NotImplementedError("Ukjent inkrementell modus: {aggregate.inkrementell}")


def _fetch_periods(
    configuration: Configuration,
    aggregate: SmallAggregate,
    config_directory: Path,
    connection: oracledb.Connection,
    *,
    input_directory: Path | None,
) -> tuple[set[int | str], set[int | str]]:
    """Henter tilgjengelige perioder fra datakilden og måltabellen."""
    if input_directory is not None:
        directory = _resolve_directory(input_directory, config_directory)
        data = lokal.read_csv(directory, aggregate)
        available = set(data[aggregate.periodisering].dropna().tolist())
    else:
        available = oracle.read_periods(
            connection, _read_sql(aggregate, config_directory), aggregate.periodisering
        )

    existing = oracle.read_target_periods(
        connection, configuration.connection.schema_name, aggregate
    )
    return available, existing


def _read_sql(aggregate: SmallAggregate, config_directory: Path) -> str:
    """Leser SQL-filen relativt til konfigurasjonen."""
    sql_path = (config_directory / aggregate.sporring_sql).resolve()
    try:
        return sql_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"SQL-filen kan ikke leses: {sql_path}") from exc


def _read_input(
    aggregate: SmallAggregate,
    config_directory: Path,
    connection: oracledb.Connection | None,
    *,
    input_directory: Path | None,
    periods_to_load: list[int | str] | None = None,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Leser aggregatdata fra CSV eller Oracle."""
    if input_directory is not None:
        directory = _resolve_directory(input_directory, config_directory)
        data = lokal.read_csv(directory, aggregate)
        if periods_to_load is not None:
            data = data[data[aggregate.periodisering].isin(periods_to_load)]
        return data, {}
    else:
        if connection is None:
            raise RuntimeError("Databasetilkobling mangler.")

        sql_text = _read_sql(aggregate, config_directory)
        data, types = oracle.read_query(
            connection, sql_text, aggregate, periods_to_load=periods_to_load
        )
        return data, types


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
    """Sender resultatet til CSV eller Oracle."""
    if output_directory is not None:
        directory = _resolve_directory(output_directory, config_directory)
        lokal.write_csv(result, directory, aggregate, dry_run=dry_run)
    else:
        _write_database(
            configuration,
            aggregate,
            result,
            source_types,
            connection,
            dry_run=dry_run,
        )


def _write_database(
        configuration: Configuration,
        aggregate: SmallAggregate,
        result: pd.DataFrame,
        source_types: dict[str, str],
        connection: oracledb.Connection | None,
        *,
        dry_run: bool,
) -> None:
    """Validerer og skriver resultatet til Oracle."""
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
    """Slår opp en mappebane relativt til konfigurasjonsfilen."""
    resolved = directory.expanduser()
    if resolved.is_absolute():
        return resolved.resolve()
    return (config_directory / resolved).resolve()
