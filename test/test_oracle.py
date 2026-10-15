from uuid import uuid4

import pandas as pd

from statistikkbank.config import SmallAggregate
from statistikkbank.oracle import write_result


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
