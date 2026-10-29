import pandas as pd
from statistikkprodukt.prikking import prikking


def test_prikking_returns_masked_data_and_control_data():
    """Sikrer at prikking returnerer prikkede data og kontrolldata med markører."""
    data = pd.DataFrame({"periode": pd.Series([202501], dtype="int64")})
    prepub, result = prikking(
        data,
        periode="periode",
        formula="~ periode",
        tallKol="antall",
        prikking=True,
        saerskilt=False,
    )
    assert list(prepub.columns) == ["periode"]
    assert prepub["periode"].dtype == data["periode"].dtype
    assert result["periode"].dtype == data["periode"].dtype
    assert result["primary"].tolist() == [True]
    assert result["suppressed"].tolist() == [True]
    assert result["primary"].dtype == bool
    assert result["suppressed"].dtype == bool
    assert list(result.columns) == ["periode", "primary", "suppressed"]
