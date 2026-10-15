# Plan: CLI for prikking av aggregater

## Goal

Create a Python CLI to perform an ETL task that reads table contents, runs an R script (using rpy2) to perform Gaussian suppression (masks small numbers, also referred to as "prikking" in Norwegian), and writes the result back to the database.

The CLI is intended to be used both manually on Linux (a sandboxed development environment called KNAST) and as part of a DAG in a production pipeline. In production, it shall run as a self-contained Docker container. Configuration is provided as a YAML file. Relative paths, including paths to SQL files, are resolved from the directory containing the configuration file.

Important domain terms are "bredde aggregater" (lots of variables) and "smale aggregater" (few variables). "Bredde aggregater" are the source from which a number of "smale aggregater" are generated. Those are masked to avoid reidentification through small numbers.

Use oracledb, ppy2 and pandas. All orchestration and interaction with the database happens in Python. R only does masking. Mock out the R invocation for now; the real implementation will be added later.

## Implementation decisions

1. **Program and package naming:** The Python distribution, import package, and executable are all named `statistikkbank`.
2. **Configuration location:** `--config` accepts a YAML file. Resolve relative paths from the directory containing that file.
3. **Oracle connection profiles:** Allowed values for `connection.database` are `DWHP`, `DWHQ`, `DWHU`, and `DWHR`. Use placeholder mappings for host, port, and service name for now.
4. **Secret references:** Support the URI forms shown in the configuration example. Google Secret Manager payloads are UTF-8 strings and may contain a flat JSON object. Allow `terminal://` only when stdin is a TTY. Fail if a referenced value is missing.
5. **SQL contract:** Pass SQL files to Oracle without pre-validating that they contain a `SELECT` statement or have no bind parameters. Returned column names must match the configured `kolonne` values. Source column types come from Oracle.
6. **Database writes:** `tabell` is the target table name. Use the configured `kolonne` values as output column names. Do not create uniqueness constraints. Write each "smalt aggregat" in one transaction. If the result has no rows, make no database changes.
7. **Incremental modes:** The modes operate on the configured period column:
   - `overskriv_ikke` appends periods that do not already exist and logs a warning for periods that already exist.
   - `overskriv_alt` replaces all periods.
   - `overskriv_siste_periode` replaces only the maximum period present in the result.
8. **Period values:** Periods may be integers, such as `YYYYMM`, or strings. Assume values of the chosen type are sortable.
9. **Schema compatibility:** Use `dba_tables`, `dba_columns`, `dba_tab_comments`, and `dba_col_comments`; all database users in the target environment may read these views. Fail for all schema differences; never create, alter, remove, or narrow columns.
10. **Metadata:** Tags may appear in any order and values may span lines until the next tag. Escaping is not supported. Duplicate tags are invalid. Metadata is not required in local CSV mode.
11. **Local CSV mode:** Specifying `--input-directory` selects CSV input; without it, input comes from the database. Specifying `--output-directory` selects CSV output; without it, output goes to the database. Both CSV files are named `{tabell}.csv` and are distinguished by their input and output directories. OBT source tables are referenced only inside the SQL query. Existing output files are overwritten. `--dry-run` performs no writes and prints what would have happened.
12. **R boundary:** `prikking` currently returns the input dataframe with one new Boolean column, `prikket`, set to `True`; all input dtypes are preserved. Persist only the input columns and `prikket`. The prepared R function sources the script directly rather than loading it as an installed R package.
13. **Language and errors:** CLI help and output, configuration validation, logs, documentation, and other user-facing errors must be in Norwegian. Exit with `0` for success, `2` for CLI or configuration errors, and `1` for operational failures.
14. **Container:** Use an Ubuntu base image and install Python and R. Defer a Chainguard-based image.
15. **Integration tests:** Tests may require Docker and use a fixed host port. CI will not run these tests in parallel.
16. **Sandboxed test environment:** Copilot runs commands in a sandbox and cannot start the Oracle container itself. Provide `testenv setup` and `testenv teardown` commands that the user runs outside the sandbox. Provide a `testenv pytest -- PYTEST_ARGS` command for the agent; it sets `STATISTIKKBANK_TESTENV_EXTERNAL=1` and forwards every argument after `--` to pytest. `test/conftest.py` detects this variable and connects to the externally managed container instead of creating an `OracleDbContainer`.

## Workflow

Outline of the program's tasks:

1. Read the configuration and validate it with Pydantic.
2. Check whether the database is reachable unless the relevant input and output are local or this is a dry run.
3. For each "smalt aggregat":
   1. Run SQL to retrieve the dataset as pandas dataframe.
   2. Run the R script, pass a dataframe, and receive a dataframe.
   3. Store the resulting dataframe in the selected database or CSV destination.

## User experience

Keep in mind that the audience is not technical. Don't expose exceptions, unless --log-level=DEBUG is specified. Show informative error messages, utilize pydantic. No unknown keys. All in Norwegian.

Do not change the database schema. If there is a mismatch, fail. Use `dba_tables` and `dba_columns` to check for compatibility.

## Configuration

Example for the configuration file
```yaml
connection:
  # selects preconfigured values for host, port, and service_name
  database: DWHP
  schema: my_schema # Set this as session default when connecting
  # Values may be literal strings or references using one of these forms:
  # user: my_username
  # user: env://MY_USER_ENV_NAME
  # user: terminal://
  # user: gsm://projects/my_project/secrets/my_secret/versions/latest
  # A final path segment extracts a key from a flat JSON object:
  user: gsm://projects/my_project/secrets/my_secret/versions/latest/username
  # Passwords must use a reference, not a literal value.
  password: gsm://projects/my_project/secrets/my_secret/versions/latest/password
  
  timeout: 30 # optional, default

# Denne delen konfigurerer hva som skal gjøres
smale_aggregater:
  - navn: Lekmansspråk
    navn_en: Human readable name
    tabell: ost_TABELLNAVN_BESKRIVENDE
    beskrivelse: >
       Dette er en beskrivelse av småaggregater. Bakgrunn, begrensninger, osv...
    beskrivelse_en: English description.
    # sti til SQL spørringen som definerer aggregatet
    sporring_sql: sporringer/ost_tabellnavn.sql
    periodisering: periode # kolonnen som angir tidsperiode
    inkrementell: overskriv_ikke | overskriv_alt | overskriv_siste_periode
    tallkolonne:
      navn: Antall A
      kolonne: antall_a
      beskrivelse: >
        Antall A måler blablabla

    # argumenter som sendes videre til R skriptet
    formula: "~ PERIODE * REGION * KJONN * ALDER"
    prikking: true
    saerskilt: false  

    variabler:
      - navn: Region
        navn_en: Region
        kolonne: region
        beskrivelse: >
          Denne variablen beskriver regionen som antall_a gjelder for.
          
          I tilfellet av sammenslåing av regioner vil den inneholde dagens verdi. 

      - navn: Periode
        navn_en: Period
        kolonne: periode
        beskrivelse: >
          Denne variablen perioden som antall_a gjelder for på månedsgranularitet.

          Formatet er YYYYMM.
```

navn, navn_en, beskrivelse and beskrivelse_en are optional. If they are not specified, read the database comments (dba_tab_comments and dba_col_comments) and parse out tags. For eksampel, a comment could be `#NAVN Min variabel #NAVN_EN My variable #BESKRIVELSE Min beskrivelse #BESKRIVELSE_EN English description`. Fail if a field is missing in both the yml file and the database. Use the logging library, log (INFO) which source is taken. If --verbose is specified, log the values as well.

## CLI

Example usage of the API. Use the argparse library. Keep the help text informative and in Norwegian. Keep in mind that the users are not technical.

```shell
# Laste ned den nyeste versjon fra github og gjør den tilgjengelig som et program
uv tool install statistikkbank@https://github.com/navikt/NavDataprodukt.git

# Vis hjelpetekst
statistikkbank --help
statistikkbank aggregat prikking --help

# Kjør prikking for hele konfigurasjon i konfigurasjon.yml
# Kan også specifieseres med env STATISTIKKBANK_AGGREGAT_CONFIG=...
statistikkbank aggregat prikking --config=konfigurasjon.yml
export STATISTIKKBANK_AGGREGAT_CONFIG=konfigurasjon.yml

# Bare vis hva som ville skjedd
statistikkbank aggregat prikking --dry-run

# kontroller logging
statistikkbank aggregat prikking --log-level=WARN
statistikkbank aggregat prikking --verbose

# Skriv til CSV i stedet for database (for eksempel til output/ost_tabellnavn_beskrivende.csv)
statistikkbank aggregat prikking --output-directory=output/

# Les fra CSV i stedet for database. Filnavnet følger verdien i `tabell`,
# for eksempel `tabell: ost_tabellnavn_beskrivende`
# -> input/ost_tabellnavn_beskrivende.csv
statistikkbank aggregat prikking --input-directory=input/

# Lokal innlesing og utskriving kan kombineres
statistikkbank aggregat prikking \
  --input-directory=input/ --output-directory=output/

# Ikke les hemmeligheter, hvis ikke det er behov for det

# Bare kjør noen småaggregater
statistikkbank aggregat prikking ost_tabellnavn_beskrivende ost_en_annen_tabellnavn_beskrivende

# Kjør disse utenfor Copilot-sandkassen for å starte og stoppe Oracle-testmiljøet
statistikkbank testenv setup
statistikkbank testenv teardown

# Kjør pytest fra sandkassen mot det eksterne testmiljøet.
# Alle argumenter etter `--` sendes uendret til pytest.
statistikkbank testenv pytest -- test/test_oracle.py -k test_skriving
```

## Project layout

Project layout:
```text
pyproject.toml
uv.lock
src/
  statistikkbank/
    __init__.py
    cli.py # argparse
    db/
      operations.py
      metadata.py
      validation.py
    prikking.py
    config.py  # pydantic models
    lokal.py # csv filer fra lokal
    testenv.py # administrasjon av eksternt Oracle-testmiljø
    app.py # glue code
test/
  conftest.py
  # pytest tester her
R/ # Remember to include the R files in the package!
  dvh_prikking.R # entrypoint when python calls R
    
```

## R integration

The application calls `prikking`, which returns a marked dataframe before starting R. `_run_r_prikking` prepares the disabled R invocation and sources the script directly:
```python
# Initialize R bridge
pandas2ri.activate()
robjects.r["source"](r_script_path)
r_prikking = robjects.globalenv["dvh_prikking"]
    
all_results = []

for sub in df[periode].unique():
    sub_df = df[df[periode] == sub]

    r_result = r_prikking(
        data = sub_df, 
        formula = config["formula"], 
        tallKol = config['smale_aggregater']['tallkolonne']['kolonne'], 
        prikking = config["prikking"], 
        saerskilt = config["saerskilt"]
    )

    # The R function returns both the aggregate and quality-check data frames.
    df_result = pandas2ri.rpy2py(r_result.rx2("smalt_aggregat"))

    # TODO: Clarify whether run information should be stored separately.
    # TODO: Clarify how to store metadata in the database.
    # df_result["run_target"] = config["tabell"]
    # df_result["applied_formula"] = config["formula"]

    all_results.append(df_result)

# 5. Union all the outputs together into one final DataFrame
final_df = pd.concat(all_results, ignore_index=True)
```

## Testing

Write pytests using Oracle testcontainers. The default behavior in `test/conftest.py` is to create and manage an `OracleDbContainer` for the test session:
```python
from testcontainers.core import testcontainers_config
from testcontainers.oracle import OracleDbContainer

oracle = OracleDbContainer(oracle_password="testpassword")
oracle.with_env("TZ", "Europe/Oslo")
oracle.with_env("ORA_SDTZ", "Europe/Oslo")

# testcontainer removed the option to specify the hostname, uses docker-engine default
# we want a fixed container such that IDE/CLI tools can connect to the db
oracle.with_bind_ports(1521, connection_config.port)

# fixed name for reuse and error messages should a container be running from before
oracle.with_name(CONTAINER_NAME)
```

### External test environment for sandboxed agents

The Oracle container must be started by the user outside the Copilot sandbox before the agent runs integration tests:

```shell
statistikkbank testenv setup
```

`testenv setup` must:

1. Use the Docker Python SDK (`docker.from_env()`) to verify that the Docker daemon is reachable.
2. Use a fixed container name, host port, credentials, timezone, and Oracle image shared with `test/conftest.py`.
3. Label containers managed by this command so teardown never removes an unrelated container with the same name.
4. If the correctly labelled container is already running, report that clearly and succeed.
5. If the correctly labelled container exists but is stopped, start it.
6. Fail with an informative Norwegian error if Docker is unavailable, the fixed port is occupied, or the name belongs to an unmanaged or incompatible container.
7. Wait until Oracle is ready to accept connections before succeeding. The container must remain running after the command exits.

The user removes the external environment with:

```shell
statistikkbank testenv teardown
```

`testenv teardown` must use the Docker SDK, stop and remove only the correctly labelled managed container, and succeed with an informative message if that container does not exist. It must fail rather than modify an unmanaged container with the same name.

The agent runs tests through:

```shell
statistikkbank testenv pytest -- PYTEST_ARGS
```

This command must:

1. Set `STATISTIKKBANK_TESTENV_EXTERNAL=1` only for the pytest subprocess.
2. Forward all arguments after `--` unchanged to pytest and return pytest's exit code.
3. Use the Docker Python SDK to look up the fixed, labelled container and verify that its status is `running`.
4. Check that Oracle is reachable at the configured fixed host and port before starting pytest. If the container or database is unavailable, fail with a Norwegian message instructing the user to run `statistikkbank testenv setup` outside the sandbox.

When `test/conftest.py` sees `STATISTIKKBANK_TESTENV_EXTERNAL=1`, it must not instantiate or start `OracleDbContainer`. It must instead use the fixed external connection settings and fail clearly if the database cannot be reached. Without the variable, tests retain the normal self-managed `OracleDbContainer` behavior for local development and CI.

Document this workflow in `.github/copilot-instructions.md` and `README_DEV.md`. Agents running inside the sandbox must use `statistikkbank testenv pytest -- ...`, never plain pytest for integration tests.

## Container and dependency updates

Write a Dockerfile using an Ubuntu base image with Python and R installed. A Chainguard-based image is deferred.

Set up dependabot, for github actions and uv. Create separate groups for security and version updates. Use a 14 day dependency cooldown.

## Documentation and example

Write three sets of documentation.
- .github/copilot-instructions.md
- a README.md for the non-technical audience
- a README_DEV.md for developers.

Create an `eksempel` folder containing `inputs/ost_befolkning_kjonn.csv`, `inputs/ost_befolkning_alder.csv`, `outputs/ost_befolkning_kjonn.csv`, `outputs/ost_befolkning_alder.csv`, a configuration file for the transformations, SQL files that refer to the OBT source tables, and a README explaining how to run the example locally.