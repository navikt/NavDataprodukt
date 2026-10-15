from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from statistikkbank.app import run
from statistikkbank.config import Configuration, resolve_secret
from statistikkbank.oracle import (
    compatible_type,
    parse_metadata,
    validate_select,
    write_result,
)
from statistikkbank.prikking import prikking
from statistikkbank.lokal import apply_incremental


def _configuration():
    return Configuration.model_validate(
        {
            "connection": {
                "database": "DWHP",
                "schema": "TEST",
                "user": "testuser",
                "password": "env://TEST_PASSWORD",
            },
            "smale_aggregater": [
                {
                    "tabell": "TABELL",
                    "sporring_sql": "select.sql",
                    "periodisering": "periode",
                    "inkrementell": "overskriv_ikke",
                    "tallkolonne": {"kolonne": "antall"},
                    "formula": "~ periode * region",
                    "prikking": True,
                    "saerskilt": False,
                    "variabler": [{"kolonne": "periode"}, {"kolonne": "region"}],
                }
            ],
        }
    )


def test_configuration_rejects_unknown_keys():
    config = _configuration().model_dump()
    config["unknown"] = True
    with pytest.raises(ValidationError):
        Configuration.model_validate(config)


def test_resolve_env_reference(monkeypatch):
    monkeypatch.setenv("TEST_PASSWORD", "secret")
    assert resolve_secret("env://TEST_PASSWORD", password=True) == "secret"


def test_mock_prikking_adds_boolean_column_and_preserves_input_dtypes():
    data = pd.DataFrame({"periode": pd.Series([202501], dtype="int64")})
    result = prikking(data)
    assert result["periode"].dtype == data["periode"].dtype
    assert result["prikket"].tolist() == [True]
    assert result["prikket"].dtype == bool
    assert list(result.columns) == ["periode", "prikket"]


def test_sql_contract_accepts_one_select_and_rejects_binds_or_multiple_statements():
    assert validate_select("SELECT 1 FROM dual;") == "SELECT 1 FROM dual"
    with pytest.raises(ValueError, match="bind"):
        validate_select("SELECT :period FROM dual")
    with pytest.raises(ValueError, match="bind"):
        validate_select("SELECT :1 FROM dual")
    with pytest.raises(ValueError, match="FOR UPDATE"):
        validate_select("SELECT 1 FROM dual FOR UPDATE")
    with pytest.raises(ValueError, match="nøyaktig én"):
        validate_select("SELECT 1 FROM dual; DELETE FROM tabell")
    assert validate_select("SELECT ';' AS value FROM dual; -- trailing") == (
        "SELECT ';' AS value FROM dual"
    )
    assert validate_select("WITH c AS (SELECT 1 value FROM dual) SELECT value FROM c").startswith(
        "WITH"
    )


def test_metadata_tags_are_order_independent_and_multiline():
    metadata = parse_metadata(
        "#BESKRIVELSE Første linje\nandre linje #NAVN Navn #NAVN_EN English"
    )
    assert metadata == {
        "BESKRIVELSE": "Første linje\nandre linje",
        "NAVN": "Navn",
        "NAVN_EN": "English",
    }
    with pytest.raises(ValueError, match="flere ganger"):
        parse_metadata("#NAVN Én #NAVN To")
    with pytest.raises(ValueError, match="flere ganger"):
        parse_metadata("#NAVN #NAVN To")


def test_csv_incremental_mode_skips_existing_periods():
    aggregate = _configuration().smale_aggregater[0]
    existing = pd.DataFrame({"periode": [202501], "region": ["Oslo"], "antall": [1]})
    incoming = pd.DataFrame(
        {
            "periode": [202501, 202502],
            "region": ["Oslo", "Oslo"],
            "antall": [2, 3],
            "prikket": [True, True],
        }
    )
    result = apply_incremental(existing, incoming, aggregate)
    assert result["periode"].tolist() == [202501, 202502]
    assert result["antall"].tolist() == [1, 3]


def test_csv_latest_period_mode_writes_only_the_latest_period_when_empty():
    aggregate = _configuration().smale_aggregater[0].model_copy(
        update={"inkrementell": "overskriv_siste_periode"}
    )
    incoming = pd.DataFrame(
        {
            "periode": [202501, 202502],
            "region": ["Oslo", "Oslo"],
            "antall": [1, 2],
            "prikket": [True, True],
        }
    )
    result = apply_incremental(pd.DataFrame(), incoming, aggregate)
    assert result["periode"].tolist() == [202502]


def test_csv_pipeline_writes_mock_result_without_database(tmp_path):
    config = _configuration()
    input_directory = tmp_path / "inputs"
    output_directory = tmp_path / "outputs"
    input_directory.mkdir()
    pd.DataFrame(
        {"periode": [202501], "region": ["Oslo"], "antall": [12]}
    ).to_csv(input_directory / "tabell.csv", index=False)

    run(
        config,
        tmp_path,
        input_format="csv",
        input_directory=Path("inputs"),
        output_format="csv",
        output_directory=Path("outputs"),
    )

    result = pd.read_csv(output_directory / "tabell.csv")
    assert result.to_dict("records") == [
        {"periode": 202501, "region": "Oslo", "antall": 12, "prikket": True}
    ]


def test_schema_compatibility_rejects_narrow_columns():
    assert compatible_type("VARCHAR2(100)", ("VARCHAR2", 100, None, None))
    assert not compatible_type("VARCHAR2(100)", ("VARCHAR2", 50, None, None))
    assert compatible_type("NUMBER(10,2)", ("NUMBER", None, 12, 3))
    assert not compatible_type("NUMBER(10,2)", ("NUMBER", None, 10, 1))
    assert compatible_type("TIMESTAMP", ("TIMESTAMP(6)", None, None, None))
    assert not compatible_type("TIMESTAMP", ("TIMESTAMP(3)", None, None, None))


def test_empty_database_result_does_not_inspect_or_mutate_connection():
    class NoDatabaseCalls:
        def __getattr__(self, name):
            raise AssertionError(f"Unexpected database call: {name}")

    aggregate = _configuration().smale_aggregater[0]
    write_result(
        NoDatabaseCalls(),
        "TEST",
        aggregate,
        pd.DataFrame(columns=["periode", "region", "antall", "prikket"]),
        {},
        migrate=False,
    )
