from pathlib import Path

import pandas as pd


def prikking(
    data: pd.DataFrame,
    periode: str,
    formula: str,
    tallKol: str,
    prikking: bool,
    saerskilt: bool,
) -> pd.DataFrame:
    """Returner foreløpig et markert datasett uten å starte R."""
    return _result_passthrough(data)
    # return _run_r_prikking(data, periode, formula, tallKol, prikking, saerskilt)


def _run_r_prikking(
    data: pd.DataFrame,
    periode: str,
    formula: str,
    tallKol: str,
    prikking: bool,
    saerskilt: bool,
) -> pd.DataFrame:
    """Kjører og samler R-resultater per periode når integrasjonen aktiveres."""
    if periode not in data.columns:
        raise ValueError(f"Periodekolonnen {periode} finnes ikke i datasettet.")

    from rpy2 import robjects
    from rpy2.robjects import pandas2ri

    pandas2ri.activate()
    r_script_path = _r_script_path()
    robjects.r["source"](str(r_script_path))
    r_prikking = robjects.globalenv["dvh_prikking"]

    all_results = []
    for period in data[periode].drop_duplicates():
        if pd.isna(period):
            subset = data[data[periode].isna()]
        else:
            subset = data[data[periode] == period]
        r_result = r_prikking(
            data=subset,
            formula=formula,
            tallKol=tallKol,
            prikking=prikking,
            saerskilt=saerskilt,
        )
        df_result = pandas2ri.rpy2py(r_result.rx2("smalt_aggregat"))
        if not isinstance(df_result, pd.DataFrame):
            raise TypeError("R-funksjonen returnerte ikke et pandas-datasett.")
        all_results.append(df_result)

    if not all_results:
        return data.iloc[0:0].copy()
    return pd.concat(all_results, ignore_index=True)


def _result_passthrough(data: pd.DataFrame) -> pd.DataFrame:
    """Legger til den foreløpige boolske prikkingmarkøren."""
    result = data.copy()
    result["prikket"] = pd.Series(True, index=result.index, dtype=bool)
    return result


def _r_script_path() -> Path:
    """Finner den pakkede dvh_prikking.R-filen."""
    module_path = Path(__file__).resolve()
    candidates = (
        module_path.parent / "R" / "dvh_prikking.R",
        module_path.parents[1] / "R" / "dvh_prikking.R",
        module_path.parents[2] / "R" / "dvh_prikking.R",
    )
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(
        "Fant ikke R-skriptet R/dvh_prikking.R i statistikkprodukt-pakken."
    )
