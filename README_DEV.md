# Utviklerhåndbok

## Utviklingsmiljø

Prosjektet bruker `uv`, Python 3.14 eller nyere, Oracle Database-driveren, pandas, Pydantic, R og rpy2.

```sh
uv sync
uv run pytest test/test_config.py
```

## Integrasjonstester med Oracle

Oracle-testmiljøet må administreres utenfor Copilot-sandkassen:

```sh
uv run statistikkbank testenv setup
uv run statistikkbank testenv teardown
```

Inne i sandkassen kjøres tester mot det eksternt startede miljøet med:

```sh
uv run statistikkbank testenv pytest -- test
```

Alle argumenter etter `--` sendes uendret videre til pytest. Kommandoen kontrollerer Docker-containeren og Oracle-tilkoblingen, og setter `STATISTIKKBANK_TESTENV_EXTERNAL=1` bare for pytest-prosessen. Kjør aldri vanlige integrasjonstester med `pytest` i sandkassen.

Uten denne miljøvariabelen administrerer `test/conftest.py` Oracle-testcontaineren for den lokale utvikleren eller CI.

## Pakking og container

`Dockerfile` bygger en Ubuntu-basert runtime med Python og R. R-skriptet i `R/` pakkes med prosjektet; Python-koden bruker foreløpig mock-funksjonen i `statistikkbank.prikking`.

Databaseprofilene `DWHP`, `DWHQ`, `DWHU` og `DWHR` har plassholderverdier i `config.py` og må konfigureres før produksjonsbruk.
