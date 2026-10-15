import pandas as pd


def prikking(data: pd.DataFrame) -> pd.DataFrame:
    """Mock for R-basert prikking. Behold datatyper og marker rader."""
    result = data.copy()
    result["prikket"] = pd.Series(True, index=result.index, dtype=bool)
    return result
