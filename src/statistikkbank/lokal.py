from pathlib import Path

import pandas as pd

from statistikkbank.config import SmallAggregate


def read_csv(directory: Path, aggregate: SmallAggregate) -> pd.DataFrame:
    path = directory / f"{aggregate.tabell}.csv"
    try:
        frame = pd.read_csv(path)
    except OSError as exc:
        raise ValueError(f"Kan ikke lese CSV-filen {path}.") from exc
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as exc:
        raise ValueError(f"CSV-filen {path} har et ugyldig format.") from exc
    validate_columns(frame, aggregate)
    return frame


def validate_columns(frame: pd.DataFrame, aggregate: SmallAggregate) -> None:
    expected = [
        variable.kolonne
        for variable in aggregate.variabler
    ] + [aggregate.tallkolonne.kolonne]
    actual_by_lower = {str(column).lower(): column for column in frame.columns}
    if len(actual_by_lower) != len(frame.columns):
        raise ValueError(f"CSV-filen for {aggregate.tabell} har kolonner med like navn.")
    missing = [column for column in expected if column.lower() not in actual_by_lower]
    unexpected = [
        column for column in frame.columns
        if str(column).lower() not in {name.lower() for name in expected}
    ]
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"mangler: {', '.join(missing)}")
        if unexpected:
            details.append(f"ukjente: {', '.join(map(str, unexpected))}")
        raise ValueError(f"Kolonnene i {aggregate.tabell}.csv stemmer ikke ({'; '.join(details)}).")
    frame.rename(
        columns={actual_by_lower[column.lower()]: column for column in expected},
        inplace=True,
    )


def write_csv(
    frame: pd.DataFrame,
    directory: Path,
    aggregate: SmallAggregate,
    *,
    dry_run: bool,
) -> None:
    path = directory / f"{aggregate.tabell}.csv"
    if frame.empty:
        print(f"Ingen rader for {aggregate.tabell}; CSV-filen endres ikke.")
        return
    existing = pd.DataFrame()
    if path.exists():
        try:
            existing = pd.read_csv(path)
        except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as exc:
            raise ValueError(f"Kan ikke lese eksisterende CSV-fil {path}.") from exc
    combined = apply_incremental(existing, frame, aggregate)
    if dry_run:
        print(f"Ville skrevet {len(combined)} rader til {path}.")
        return
    directory.mkdir(parents=True, exist_ok=True)
    combined.to_csv(path, index=False)


def apply_incremental(
    existing: pd.DataFrame, result: pd.DataFrame, aggregate: SmallAggregate
) -> pd.DataFrame:
    mode = aggregate.inkrementell
    if mode == "overskriv_alt":
        return result.copy()

    period = aggregate.periodisering
    if period not in result or (not existing.empty and period not in existing):
        raise ValueError(f"Periodekolonnen {period} mangler i CSV-resultatet.")
    if mode == "overskriv_siste_periode":
        latest = result[period].max()
        retained = (
            existing[existing[period] != latest]
            if not existing.empty
            else existing
        )
        new_rows = result[result[period] == latest]
        return pd.concat([retained, new_rows], ignore_index=True)
    if existing.empty:
        return result.copy()

    available = set(existing[period].dropna().tolist())
    incoming = result[period].dropna()
    duplicates = sorted(set(incoming[incoming.isin(available)].tolist()), key=str)
    if duplicates:
        import logging

        logging.getLogger(__name__).warning(
            "Periodene %s finnes allerede i %s og hoppes over.",
            ", ".join(map(str, duplicates)),
            aggregate.tabell,
        )
    new_rows = result[~result[period].isin(available)]
    return pd.concat([existing, new_rows], ignore_index=True)
