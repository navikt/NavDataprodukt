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
    if periode not in data.columns:
        raise ValueError(f"Periodekolonnen {periode} finnes ikke i datasettet.")
    import rpy2.robjects as robjects
    import rpy2.robjects.packages as rpackages
    from rpy2.robjects.vectors import StrVector
    from rpy2.robjects import pandas2ri
    from rpy2.robjects.conversion import localconverter

    # 1. Bootstrap the 'pak' installation if it doesn't exist in your R library
    if not rpackages.isinstalled('pak'):
        print("Installing 'pak' package in R...")
        utils = rpackages.importr('utils')
        # Select the primary CRAN mirror for stable network downloads
        utils.chooseCRANmirror(ind=1)
        utils.install_packages(StrVector(['pak']))

    # 2. Safely import 'pak' now that it is guaranteed to be installed
    pak = rpackages.importr('pak')

    # 3. Use 'pak' to safely pull your custom Norwegian NAV package from GitHub
    # Note: R's pak::pak() points to the underlying pkg_install function
    print("Installing 'NavDataprodukt' via pak...")
    # pak.pkg_install("navikt/statistikkprodukt-metode/NavDataprodukt") #, upgrade=True)

    # 4. Load your new package
    importr = rpackages.importr
    importr('NavDataprodukt')

    # 5. Access the environment objects
    r_prikking = robjects.r('dvh_prikking')
    print("Successfully loaded 'dvh_prikking'!")

    all_results_smalt = []
    all_results_kontroll = []

    for period in data[periode].drop_duplicates():
        if pd.isna(period):
            subset = data[data[periode].isna()]
        else:
            subset = data[data[periode] == period]

        # CRITICAL CHANGE: Use a localconverter context so rpy2 automatically
        # translates 'subset' (Pandas DataFrame) into an R data.frame inside the function.
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
    result["prikket"] = pd.Series(True, index=result.index, dtype=bool)
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
