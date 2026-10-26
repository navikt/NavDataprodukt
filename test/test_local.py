from pathlib import Path

import pandas as pd
from statistikkprodukt.app import run
from test.test_config import configuration


def test_csv_pipeline_writes_marked_result_without_database(tmp_path):
    """Kjører CSV-pipelinen uten database og skriver prikkingmarkør."""
    config = configuration()
    input_directory = tmp_path / "inputs"
    output_directory = tmp_path / "outputs"
    input_directory.mkdir()
    pd.DataFrame(
        {"periode": [202501], "region": ["Oslo"], "antall": [12]}
    ).to_csv(input_directory / "tabell.csv", index=False)

    run(
        config,
        tmp_path,
        input_directory=Path("inputs"),
        output_directory=Path("outputs"),
    )

    result = pd.read_csv(output_directory / "tabell.csv")
    assert result.to_dict("records") == [
        {"periode": 202501, "region": "Oslo", "antall": 12, "prikket": True}
    ]
