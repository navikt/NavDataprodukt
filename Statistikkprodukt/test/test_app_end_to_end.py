from uuid import uuid4

from statistikkprodukt import app
from statistikkprodukt.config import DATABASE_PROFILES, load_configuration
from statistikkprodukt.testenv import (
    CONTAINER_PORT,
    ORACLE_PASSWORD,
    ORACLE_SERVICE,
    ORACLE_USER,
)


def test_create_tables_and_run_loads_grouped_obt_data(
        oracle_connection, monkeypatch, tmp_path
):
    """Oppretter og fyller ett småaggregat fra en OBT-tabell."""
    suffix = uuid4().hex[:12]
    source_table = f"obt_e2e_{suffix}"
    aggregate_table = f"agg_e2e_{suffix}"
    aggregate_directory = tmp_path / "aggregater"
    aggregate_directory.mkdir()

    monkeypatch.setenv("STATISTIKKPRODUKT_E2E_PASSWORD", ORACLE_PASSWORD)
    monkeypatch.setitem(
        DATABASE_PROFILES,
        "DWHP",
        {
            "host": "127.0.0.1",
            "port": CONTAINER_PORT,
            "service_name": ORACLE_SERVICE,
        },
    )
    monkeypatch.setattr(
        app,
        "prikking",
        lambda data, **_: data.assign(prikket=True),
    )

    (tmp_path / "konfigurasjon.yml").write_text(
        f"""
connection:
  database: DWHP
  schema: SYSTEM
  user: {ORACLE_USER}
  password: env://STATISTIKKPRODUKT_E2E_PASSWORD
mapper:
  - aggregater/**
smale_aggregater:
  - {aggregate_table}
""",
        encoding="utf-8",
    )
    (aggregate_directory / f"{aggregate_table}.yml").write_text(
        f"""
definisjon:
  obt_tabell: {source_table}
  navn: Aggregerte verdier
  navn_en: Aggregated values
  innhold: Verdier gruppert etter periode og region.
  innhold_en: Values grouped by period and region.
  periodisering: periode
  inkrementell: overskriv_alt
  tallkolonne:
    navn: Antall
    navn_en: Count
    kolonne: antall
    innhold: Summert antall.
    innhold_en: Summed count.
  formula: "~ periode * region"
  prikking: true
  saerskilt: false
  variabler:
    - navn: Periode
      navn_en: Period
      kolonne: periode
      innhold: Periode.
      innhold_en: Period.
    - navn: Region
      navn_en: Region
      kolonne: region
      innhold: Geografisk område.
      innhold_en: Geographic area.
""",
        encoding="utf-8",
    )
    (aggregate_directory / f"{aggregate_table}.sql").write_text(
        f"""
select periode, region, sum(antall) as antall
from {source_table}
group by periode, region
""",
        encoding="utf-8",
    )

    try:
        with oracle_connection.cursor() as cursor:
            cursor.execute(
                f"CREATE TABLE SYSTEM.{source_table} ("
                "periode NUMBER(6), region VARCHAR2(100), antall NUMBER)"
            )
            cursor.executemany(
                f"INSERT INTO SYSTEM.{source_table} VALUES (:1, :2, :3)",
                [
                    (202501, "Oslo", 10),
                    (202501, "Oslo", 5),
                    (202501, "Bergen", 7),
                    (202502, "Oslo", 3),
                ],
            )
        oracle_connection.commit()

        configuration, config_directory = load_configuration(
            tmp_path / "konfigurasjon.yml"
        )

        app.create_tables(
            configuration, config_directory, create_in_database=True
        )
        app.run(configuration, config_directory)

        with oracle_connection.cursor() as cursor:
            cursor.execute(
                f"SELECT periode, region, antall, prikket "
                f"FROM SYSTEM.{aggregate_table} ORDER BY periode, region"
            )
            loaded_rows = cursor.fetchall()

        assert loaded_rows == [
            (202501, "Bergen", 7, 1),
            (202501, "Oslo", 15, 1),
            (202502, "Oslo", 3, 1),
        ]
    finally:
        with oracle_connection.cursor() as cursor:
            for table in (aggregate_table, source_table):
                cursor.execute(
                    "SELECT 1 FROM all_tables "
                    "WHERE owner = 'SYSTEM' AND table_name = :table_name",
                    table_name=table.upper(),
                )
                if cursor.fetchone():
                    cursor.execute(f"DROP TABLE SYSTEM.{table} PURGE")
        oracle_connection.commit()
