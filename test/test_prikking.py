import pandas as pd
from statistikkprodukt.prikking import prikking


def test_prikking_adds_boolean_column_and_preserves_input_dtypes():
    """Sikrer at prikking legger til markør uten å endre inndatatyper."""
    data = pd.DataFrame({"periode": pd.Series([202501], dtype="int64")})
    result = prikking(
        data,
        periode="periode",
        formula="~ periode",
        tallKol="antall",
        prikking=True,
        saerskilt=False,
    )
    assert result["periode"].dtype == data["periode"].dtype
    assert result["prikket"].tolist() == [True]
    assert result["prikket"].dtype == bool
    assert list(result.columns) == ["periode", "prikket"]
