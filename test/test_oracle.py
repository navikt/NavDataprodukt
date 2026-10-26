from uuid import uuid4

import pandas as pd
import pytest

from statistikkprodukt.config import InkrementalMode, SmallAggregate
from statistikkprodukt import app, oracle
from statistikkprodukt.oracle import (
    write_result,
    compatible_type,
    parse_metadata,
    read_periods,
    read_query,
    read_target_periods,
)
from test.test_config import configuration


def test_metadata_tags_are_order_independent_and_multiline():
    """Parser metadata uavhengig av rekkefølge og linjeskift."""
    metadata = parse_metadata(
        "#BESKRIVELSE Første linje\nandre linje #NAVN Navn #NAVN_EN English"
    )
    assert metadata.model_dump() == {
        "beskrivelse": "Første linje\nandre linje",
        "navn": "Navn",
        "navn_en": "English",
        "beskrivelse_en": None,
    }
    with pytest.raises(ValueError, match="flere ganger"):
        parse_metadata("#NAVN Én #NAVN To")
    with pytest.raises(ValueError, match="flere ganger"):
        parse_metadata("#NAVN #NAVN To")



def test_schema_compatibility_rejects_narrow_columns():
    """Kontrollerer kompatibilitet for Oracle-tegn-, tall- og tidsstempler."""
    assert compatible_type("VARCHAR2(100)", ("VARCHAR2", 100, None, None))
    assert not compatible_type("VARCHAR2(100)", ("VARCHAR2", 50, None, None))
    assert compatible_type("NUMBER(10,2)", ("NUMBER", None, 12, 3))
    assert not compatible_type("NUMBER(10,2)", ("NUMBER", None, 10, 1))
    assert compatible_type("TIMESTAMP", ("TIMESTAMP(6)", None, None, None))
    assert not compatible_type("TIMESTAMP", ("TIMESTAMP(3)", None, None, None))


def test_empty_database_result_does_not_inspect_or_mutate_connection():
    """Sikrer at tomme resultater ikke utfører databaseoperasjoner."""
    class NoDatabaseCalls:
        def __getattr__(self, name):
            """Feiler testen dersom en metode eller egenskap brukes."""
            raise AssertionError(f"Unexpected database call: {name}")

    aggregate = configuration().smale_aggregater[0]
    write_result(
        NoDatabaseCalls(),
        "TEST",
        aggregate,
        pd.DataFrame(columns=["periode", "region", "antall", "prikket"]),
        {},
    )


@pytest.mark.parametrize("periods", [None, [], [202502], [202501, 202502]])
def test_read_query_filters_periods_in_oracle(oracle_connection, periods):
    sql = (
        "SELECT 202501 AS periode, 'Oslo' AS region, 10 AS antall FROM dual "
        "UNION ALL SELECT 202502, 'Oslo', 20 FROM dual;"
    )
    aggregate = configuration().smale_aggregater[0]
    assert read_periods(oracle_connection, sql, "periode") == {202501, 202502}

    frame, types = read_query(
        oracle_connection, sql, aggregate, periods_to_load=periods
    )
    assert sorted(frame["periode"].tolist()) == ([202501, 202502] if periods is None else periods)
    assert set(types) == {"periode", "region", "antall"}


def test_read_query_binds_string_periods_in_oracle(oracle_connection):
    period = "x') OR 1=1 --"
    sql = (
        "SELECT 'x'') OR 1=1 --' AS periode, 'Oslo' AS region, 10 AS antall FROM dual "
        "UNION ALL SELECT '2025-02', 'Oslo', 20 FROM dual"
    )
    frame, _ = read_query(
        oracle_connection, sql, configuration().smale_aggregater[0], periods_to_load=[period]
    )
    assert frame["periode"].tolist() == [period]


def test_read_target_periods_uses_configured_schema(oracle_connection):
    table = f"sb_test_{uuid4().hex[:12]}"
    aggregate = configuration().smale_aggregater[0].model_copy(update={"tabell": table})
    try:
        with oracle_connection.cursor() as cursor:
            cursor.execute(f"CREATE TABLE SYSTEM.{table} (periode NUMBER(6,0))")
            cursor.executemany(
                f"INSERT INTO SYSTEM.{table} (periode) VALUES (:1)",
                [(202501,), (202502,), (202502,)],
            )
        assert read_target_periods(oracle_connection, "SYSTEM", aggregate) == {202501, 202502}
    finally:
        with oracle_connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE SYSTEM.{table} PURGE")
        oracle_connection.commit()


def test_read_query_handles_more_than_1000_periods_in_oracle(oracle_connection):
    frame, _ = read_query(
        oracle_connection,
        "SELECT 202501 AS periode, 'Oslo' AS region, 10 AS antall FROM dual",
        configuration().smale_aggregater[0],
        periods_to_load=list(range(202000, 203001)),
    )
    assert frame["periode"].tolist() == [202501]


@pytest.mark.parametrize(
    ("mode", "loaded", "expected"),
    [
        (
            "overskriv_ikke",
            [202503],
            [(202500, 0), (202501, 1), (202502, 2), (202503, 30)],
        ),
        (
            "overskriv_alt",
            [202501, 202502, 202503],
            [(202500, 0), (202501, 10), (202502, 20), (202503, 30)],
        ),
        (
            "overskriv_siste_periode",
            [202503],
            [(202500, 0), (202501, 1), (202502, 2), (202503, 30)],
        ),
    ],
)
def test_process_aggregate_only_masks_selected_periods(
    oracle_connection, monkeypatch, tmp_path, mode, loaded, expected
):
    table = f"sb_test_{uuid4().hex[:12]}"
    config = configuration()
    config.connection.schema_name = "system"
    aggregate = config.smale_aggregater[0]
    aggregate.tabell = table
    aggregate.inkrementell = InkrementalMode(mode)
    (tmp_path / aggregate.sporring_sql).write_text(
        "SELECT 202501 AS periode, 'Oslo' AS region, 10 AS antall FROM dual "
        "UNION ALL SELECT 202502, 'Oslo', 20 FROM dual "
        "UNION ALL SELECT 202503, 'Oslo', 30 FROM dual;"
    )
    original_prikking = app.prikking
    # == periods passed to prikking will be loaded in the database.
    # Store those here to use in an assert later on
    masked_periods = []

    # Record the periods passed to masking, independently of the resulting table contents.
    def mask(data, **kwargs):
        masked_periods.extend(data["periode"].tolist())
        return original_prikking(data, **kwargs)

    monkeypatch.setattr(app, "prikking", mask)
    monkeypatch.setattr(oracle, "read_metadata", lambda *args: None)
    try:
        with oracle_connection.cursor() as cursor:
            cursor.execute(
                f"CREATE TABLE SYSTEM.{table} ("
                "periode NUMBER, region VARCHAR2(100), "
                "antall NUMBER, prikket NUMBER(1))"
            )
            cursor.executemany(
                f"INSERT INTO SYSTEM.{table} VALUES (:1, :2, :3, :4)",
                [(202500, "Oslo", 0, 1), (202501, "Oslo", 1, 1), (202502, "Oslo", 2, 1)],
            )
            if mode == "overskriv_siste_periode":
                # Make 202503 the existing latest period so this mode must replace it.
                cursor.execute(
                    f"INSERT INTO SYSTEM.{table} VALUES (:1, :2, :3, :4)",
                    [202503, "Oslo", 3, 1],
                )

        app._process_aggregate(
            config,
            aggregate,
            tmp_path,
            oracle_connection,
            input_directory=None,
            output_directory=None,
            dry_run=False,
        )

        assert sorted(masked_periods) == loaded
        with (oracle_connection.cursor() as cursor):
            cursor.execute(f"SELECT periode, antall FROM SYSTEM.{table} ORDER BY periode")
            available = cursor.fetchall()
            assert available == expected
    finally:
        with oracle_connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE SYSTEM.{table} PURGE")
        oracle_connection.commit()
