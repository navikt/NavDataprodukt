from pathlib import Path

import pandas as pd
from statistikkprodukt.app import run
from statistikkprodukt.config import StorageOption
from test.test_config import configuration


def test_csv_pipeline_writes_marked_result_without_database(tmp_path):
    """Kjører CSV-pipelinen uten database og skriver prikkingmarkør."""
    config = configuration()
    input_directory = tmp_path / "data_inn"
    output_directory = tmp_path / "data_ut"
    input_directory.mkdir()
    pd.DataFrame(
        {"periode": [202501], "region": ["Oslo"], "antall": [12]}
    ).to_csv(input_directory / "tabell.csv", index=False)

    run(
        config,
        tmp_path,
        StorageOption.CSV,
        StorageOption.CSV,
        input_directory,
        output_directory
    )

    result = pd.read_csv(output_directory / "tabell.csv")
    assert result.to_dict("records") == [
        {"periode": 202501, "region": "Oslo", "antall": 12, "prikket": True}
    ]
