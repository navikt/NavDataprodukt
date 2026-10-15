Create a python CLI to perform a ETL task that reads table contents, runs an R script (using rpy2) to perform gaussian suppression (masks small numbers, also refered to as "prikking" in norwegian) and write the result back to the database. 

The CLI is intended to be used both manually on linux (sandboxed dev environment called KNAST) and as part of a DAG in a production pipeline. In production, it shall run as a self contained docker container. All configuration must be provided by the user in a directory, which contains yml and sql files.

Important domain terms is are "bredde aggegater" (lots of variables) and "smale aggregater" (few variables). "Bredde aggregater" are the source from which a number of "smale aggregater" are generated. Those are masked, to avoid reidentifaction through small numbers.

Use oracledb and pandas. All orchestration and interaction with the database happens in python. R only does masking. Mock out the R invocation for now, I'll add it later.

Outline of the programs tasks:
1. Read the configuration and validate with pydantic. 
2. Check if the database is reachable (unless local processing or dry run)
3. For each "smal aggregat"
   1. Run SQL to retrieve the dataset as pandas dataframe.
   2. Run the R skript, pass a data frame, receive a data frame
   3. Store the 

Keep in mind that the audience is not technical. Don't expose exceptions, unless --log-level=DEBUG is specified. Show informative error messages, utilize pydantic. No unknown keys. All in Norwegian.

By default, do not change the database schema. If there is a mismatch, fail. Create a "migrate" option to update the schema. This is to be able to minimize permissions of the user. Use `dba_tables` and `dba_columns` to check for compatibility.

Example for the configuration file
#+begin_src
connection:
  # selects preconfigured values for host, port, and service_name
  database: dvh_p
  schema: my_schema # Set this as session default when connecting
  # May be specified as string
  user: host
  # or with a URL. Available options:
  # Google Secret manager
  user: gsm://projects/my_project/secrets/my_secret/versions/latest
  # Support unpacking json (only flat dictionaries + key)
  user: gsm://projects/my_project/secrets/my_secret/versions/latest/username
  # Environment variables
  user: env://MY_USER_ENV_NAME
  # Prompting from terminal
  user: terminal://
  # Fail if the password is specified as anything other then an URL
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
    sporring_sql: sporringer/ost_tabellnavn. 
    periodisering: variable_navn # indikerertidsperiode
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
#+end_src

navn, navn_en, beskrivelse and beskrivelse_en are optional. If they are not specified, read the database comments (dba_tab_comments and dba_col_comments) and parse out tags. For eksampel, a comment could be `#NAVN Min variabel #NAVN_EN My variable #BESKRIVELSE Min beskrivelse #BESKRIVELSE_EN English description`. Fail if a field is missing in both the yml file and the database. Use the logging library, log (INFO) which source is taken. If --verbose is specified, log the values as well.

Example usage of the API. Use the argparse library. Keep the help text informative and in Norwegian. Keep in mind that the users are not technical.

#+begin_src 
# Laste ned den nyeste versjon fra github og gjør den tilgjengelig som et program
uv tool install statistikkbank@https://github.com/navikt/NavDataprodukt.git

# Vis hjelpetekst
statistikkbank --help
statistikkbank aggregat prikking --help
statistikkbank aggregat migrer --help

# Kjør prikking for hele konfigurasjon i konfigurasjon.yml
# Kan også specifieseres med env STATISTIKKBANK_AGGREGAT_CONFIG=...
statistikkbank aggregat prikking --config=konfigurasjon.yml
export STATISTIKKBANK_AGGREGAT_CONFIG=konfigurasjon.yml

# Bare vis hva som ville skjedd
statistikkbank aggregat prikking --dry-run
statistikkbank aggregat migrer --dry-run

# kontroller logging
statistikkbank aggregat prikking --log-level=WARN
statistikkbank aggregat prikking --verbose

# Skriv til CSV i stedet for database (for eksempel til output/obt_tabellnavn_beskrivende.csv), for lokal testing
statistikkbank aggregat prikking --format=csv --output-directory=output/

# Les fra CSV i stedet for database (for eksempel fra input/obt_tabellnavn_beskrivende.csv), for lokal testing
statistikkbank aggregat prikking --format=csv --input-directory=input/

# Ikke les hemmeligheter, hvis ikke det er behov for det

# Bare kjør noen småaggregater
statistikkbank aggregat prikking ost_tabellnavn_beskrivende ost_en_annen_tabellnavn_beskrivende
statistikkbank aggregat migrer ost_tabellnavn_beskrivende ost_en_annen_tabellnavn_beskrivende
#+end_src


Project layout:
#+begin_src 
pyproject.toml
uv.lock
src/
  navdataprodukt/
    __init__.py
    cli.py # argparse
    oracle.py
    prikking.py
    config.py  # pydantic models
    lokal.py # csv filer fra lokal
    app.py # glue code
test/
  # pytest tester her
R/ # Remember to include the R files in the package!
  dvh_prikking.R # entrypoint when python calls R
    
#+end_src

To run the R skript (you can write the function, but don't call it yet / comment out the invocatrion)
#+begin_src 
# Initialize R bridge
pandas2ri.activate()
robjects.r('library(NavDataprodukt)')
# Stored in R/dvh_prikking.R
r_prikking = robjects.r('dvh_prikking')
    
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

    # Convert R result back to pandas
    df_result = pandas2ri.rpy2py(r_result)

    # Add metadata tracking columns so you can differentiate the runs
    df_result["run_target"] = conf["target_table"]
    df_result["applied_formula"] = conf["formula"]

    all_results.append(df_result)

# 5. Union all the outputs together into one final DataFrame
final_df = pd.concat(all_results, ignore_index=True)
#+end_src

Write pytests using oracle test containers.
#+begin_src 
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
#+end_src

Write a Dockerfile. I want to use chainguard images, but we only have the python one available and I'm not sure if I can get the R runtime in there.

Set up dependabot, for github actions and uv. Create separate groups for security and version updates. Use a 14 day dependency cooldown.

Write three sets of documentation.
- .github/copilot-instructions.md
- a README.md for the non-technical audience
- a README_DEV.md for developers.

Create a "eksempel" folder, which contains inputs/obt_befolkning.csv, outputs/ost_befolkning_kjonn.csv, outputs/ost_befolkning_alder.csv, and a configuration file that configures the transformation, and a README file that explains how to run the example locally.