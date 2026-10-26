# Utviklerhåndbok

## Prosjektlayout

```text
pyproject.toml # specification av python prosjektet 
uv.lock # lock-fil for avhengigheter
src/
  statistikkprodukt/
    __init__.py
    cli.py # CLI argumenter
    oracle/
      operations.py # connect / write_result
      metadata.py # lese metadata (e.g. kommentarer) fra DB
      validation.py # kompatibilitet av kolonnetyper
    prikking.py # kjør R skriptet
    config.py # pydantic models for konfigurasjonsfilen
    lokal.py # lesing/skriving av csv filer
    testenv.py # administrasjon av eksternt Oracle-testmiljø
    app.py # syr sammen applikasjonen
test/
  conftest.py # start testmiljø før testene starter
  # pytest tester her
R/
  dvh_prikking.R # entrypoint when python calls R
```

## Utviklingsmiljø

Prosjektet bruker `uv`, Python 3.14 eller nyere, Oracle Database-driveren, pandas, Pydantic, R og rpy2.

```sh
uv sync
uv run pytest test/test_config.py
```

## Integrasjonstester med Oracle

Oracle-testmiljøet må administreres utenfor Copilot-sandkassen:

```sh
uv run statistikkprodukt testenv setup
uv run statistikkprodukt testenv teardown
```

Inne i sandkassen kjøres tester mot det eksternt startede miljøet med:

```sh
uv run statistikkprodukt testenv pytest
# eller med argumenter:
uv run statistikkprodukt testenv pytest -- -q
```

Utenfor sandkassen håndteres testmiljøet automatisk.