from uuid import uuid4

import pandas as pd
import pytest

from statistikkbank.config import SmallAggregate
from statistikkbank.oracle import write_result, compatible_type, parse_metadata
from test.test_config import configuration


def test_write_result_appends_only_new_periods(oracle_connection):
    """Sikrer at Oracle-skriving legger til nye perioder uten duplikater."""
    table = f"sb_test_{uuid4().hex[:12]}"
    aggregate = SmallAggregate.model_validate(
        {
            "tabell": table,
            "sporring_sql": "unused.sql",
            "periodisering": "periode",
            "inkrementell": "overskriv_ikke",
            "tallkolonne": {"kolonne": "antall"},
            "formula": "~ periode * region",
            "prikking": True,
            "saerskilt": False,
            "variabler": [{"kolonne": "periode"}, {"kolonne": "region"}],
        }
    )
    first = pd.DataFrame(
        {
            "periode": [202501, 202502],
            "region": ["Oslo", "Oslo"],
            "antall": [10, 20],
            "prikket": [True, True],
        }
    )
    second = pd.DataFrame(
        {
            "periode": [202502, 202503],
            "region": ["Oslo", "Oslo"],
            "antall": [25, 30],
            "prikket": [True, True],
        }
    )
    source_types = {
        "periode": "NUMBER(6,0)",
        "region": "VARCHAR2(100)",
        "antall": "NUMBER(10,0)",
    }
    try:
        with oracle_connection.cursor() as cursor:
            cursor.execute(
                f"CREATE TABLE SYSTEM.{table} ("
                "periode NUMBER(38,0), region VARCHAR2(4000), "
                "antall NUMBER(38,0), prikket NUMBER(1))"
            )
        write_result(
            oracle_connection,
            "SYSTEM",
            aggregate,
            first,
            source_types,
        )
        write_result(
            oracle_connection,
            "SYSTEM",
            aggregate,
            second,
            source_types,
        )
        with oracle_connection.cursor() as cursor:
            cursor.execute(
                f"SELECT periode, antall FROM SYSTEM.{table} ORDER BY periode"
            )
            assert [(int(period), int(count)) for period, count in cursor.fetchall()] == [
                (202501, 10),
                (202502, 20),
                (202503, 30),
            ]
    finally:
        with oracle_connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_name FROM user_tables WHERE table_name = :table_name",
                table_name=table.upper(),
            )
            if cursor.fetchone():
                cursor.execute(f"DROP TABLE SYSTEM.{table} PURGE")
        oracle_connection.commit()


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
