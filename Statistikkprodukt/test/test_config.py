from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from statistikkprodukt.app import run
from statistikkprodukt.config import Configuration, resolve_secret
from statistikkprodukt.oracle import (
    compatible_type,
    parse_metadata,
    write_result,
)


def configuration():
    """Bygger en gyldig konfigurasjon for en liten aggregattabell."""
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
    """Sikrer at ukjente konfigurasjonsnøkler avvises."""
    config = configuration().model_dump()
    config["unknown"] = True
    with pytest.raises(ValidationError):
        Configuration.model_validate(config)


def test_resolve_env_reference(monkeypatch):
    """Slår opp miljøvariabelreferanser for hemmeligheter."""
    monkeypatch.setenv("TEST_PASSWORD", "secret")
    assert resolve_secret("env://TEST_PASSWORD", password=True) == "secret"

