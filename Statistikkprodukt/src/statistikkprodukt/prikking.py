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
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Kjører og samler R-resultater per periode når integrasjonen aktiveres."""
    import rpy2.robjects as robjects
    import rpy2.robjects.packages as rpackages
    from rpy2.robjects import pandas2ri
    from rpy2.robjects.conversion import localconverter

    if periode not in data.columns:
        raise ValueError(f"Periodekolonnen {periode} finnes ikke i datasettet.")

    importr = rpackages.importr
    try:
        importr('NavDataprodukt')
    except rpackages.LibraryError as exc:
        raise RuntimeError(
            "R-pakken 'NavDataprodukt' er ikke installert. Kjør 'statistikkprodukt installer-pakker' for å installere den."
        ) from exc

    # 5. Access the environment objects
    r_prikking = robjects.r('dvh_prikking')

    all_results_smalt = []
    all_results_kontroll = []

    for period in data[periode].drop_duplicates():
        if pd.isna(period):
            subset = data[data[periode].isna()]
        else:
            subset = data[data[periode] == period]

        # localconverter konverterer automatisk fra R til pandas data frames
        with localconverter(robjects.default_converter + pandas2ri.converter):
            df_smalt, df_kontroll = r_prikking(
                data=subset,
                formula=formula,
                tallKol=tallKol,
                prikking=prikking,
                saerskilt=saerskilt,
            )
        if not isinstance(df_smalt, pd.DataFrame):
            raise TypeError("R-funksjonen returnerte ikke et pandas-datasett for 'smalt_aggregat'.")
        all_results_smalt.append(df_smalt)

        if not isinstance(df_kontroll, pd.DataFrame):
            raise TypeError(f"R-funksjonen returnerte ikke et pandas-datasett for 'kvalitetssikring'.")
        all_results_kontroll.append(df_kontroll)

    if not all_results_smalt:
        empty_df = data.iloc[0:0].copy()
        return empty_df, empty_df.copy()

    final_smalt = pd.concat(all_results_smalt, ignore_index=True)
    final_kontroll = pd.concat(all_results_kontroll, ignore_index=True)

    # Returner DataFrames som tuple
    return final_smalt, final_kontroll


def _result_passthrough(data: pd.DataFrame) -> pd.DataFrame:
    """Legger til den foreløpige boolske prikkingmarkøren."""
    result = data.copy()
    result["primary"] = pd.Series(True, index=result.index, dtype=bool)
    result["suppressed"] = pd.Series(True, index=result.index, dtype=bool)
    return result

# def _r_script_path() -> Path:
#    """Finner den pakkede dvh_prikking.R-filen."""
#    module_path = Path(__file__).resolve()
#    candidates = (
#        module_path.parent / "R" / "dvh_prikking.R",
#        module_path.parents[1] / "R" / "dvh_prikking.R",
#        module_path.parents[2] / "R" / "dvh_prikking.R",
#    )
#    for path in candidates:
#        if path.is_file():
#            return path
#    raise FileNotFoundError(
#        "Fant ikke R-skriptet R/dvh_prikking.R i pakken."
#    )
