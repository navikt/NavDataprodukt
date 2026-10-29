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

## Konfigurasjon

`--config` peker på en YAML-fil med databaseinnstillinger, søkemønstre i `mapper` og listen `smale_aggregater` over hvilke aggregater som skal kjøres. Mønstrene finner aggregatfilene; de velger ikke aggregatene. Hvert aggregatnavn må være unikt og samsvare med YAML-filens navn. `tabell` utledes fra filnavnet, og `sporring_sql` blir samme relative sti med `.sql`-endelse. SQL-stien er relativ til hovedkonfigurasjonen, for eksempel gir `sporringer/ost_befolkning_alder.yml` tabellen `ost_befolkning_alder` og SQL-filen `sporringer/ost_befolkning_alder.sql`.

`statistikkprodukt skjema opprett` bruker samme konfigurerte Oracle-tilkobling til SQL-kilde og måltabell. Den skriver DDL med `WHERE 1 = 0` og kolonnekommentarer til standard output; `--db` utfører DDL-en i databasen. Tabeller som allerede finnes, hoppes over og logges.

```yaml
connection:
  # Velg enten profil ...
  database: DWHP
  # ... eller oppgi alle verdiene direkte i stedet:
  # host: oracle.example.no
  # port: 1521
  # service: ORCL
  schema: STATISTIKKPRODUKT
  user: env://ORACLE_USER
  password: env://ORACLE_PASSWORD
mapper:
  - aggregater/**
smale_aggregater:
  - ost_befolkning_alder
  - ost_befolkning_kjonn
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