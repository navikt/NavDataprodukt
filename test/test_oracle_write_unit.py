import pandas as pd

from statistikkbank.config import SmallAggregate
from statistikkbank.oracle import write_result


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.query = ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, **kwargs):
        self.query = query
        self.connection.queries.append((query, kwargs))

    def fetchone(self):
        return (1,)

    def fetchall(self):
        if "FROM dba_columns" in self.query:
            return [
                ("PERIODE", "NUMBER", 22, 38, 0),
                ("REGION", "VARCHAR2", 4000, None, None),
                ("ANTALL", "NUMBER", 22, 38, 0),
                ("PRIKKET", "NUMBER", 22, 1, 0),
            ]
        return [(202502,)]

    def executemany(self, query, rows):
        self.connection.inserted = (query, rows)


class FakeConnection:
    def __init__(self):
        self.queries = []
        self.inserted = None
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_write_result_inserts_only_new_periods_in_one_transaction():
    connection = FakeConnection()
    aggregate = SmallAggregate.model_validate(
        {
            "tabell": "tabell",
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
    result = pd.DataFrame(
        {
            "periode": [202502, 202503],
            "region": ["Oslo", "Oslo"],
            "antall": [2, 3],
            "prikket": [True, True],
        }
    )

    write_result(
        connection,
        "TEST",
        aggregate,
        result,
        {
            "periode": "NUMBER(6,0)",
            "region": "VARCHAR2(100)",
            "antall": "NUMBER(10,0)",
        },
    )

    query, rows = connection.inserted
    assert query == (
        "INSERT INTO test.tabell (periode, region, antall, prikket) "
        "VALUES (:1, :2, :3, :4)"
    )
    assert rows == [(202503, "Oslo", 3, 1)]
    assert connection.commits == 1
    assert connection.rollbacks == 0
