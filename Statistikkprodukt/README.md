# Statistikkprodukt

`statistikkprodukt` lager små statistikkaggregater og markerer rader som er behandlet av prikking. Verktøyet kan hente data fra Oracle eller lokale CSV-filer og lagre resultatet i Oracle eller CSV.

Denne filen er brukerdokumentasjon. [README_DEV.md](README_DEV.md) er utviklerhåndbok.

## Kom i gang

Installer Python 3.14 eller nyere, R og pakkene fra prosjektet:

```sh
uv sync
uv run statistikkprodukt --help
```

Kjør eksemepelet, som leser to CSV-filer fra `eksempel/inputs/` og skriver resultatene til `eksempel/outputs/`, uten Oracle-tilkobling eller hemmeligheter:

```sh
uv run statistikkprodukt last \
  --config eksempel/konfigurasjon.yml \
  --input-directory inputs/ \
  --output-directory outputs/
```

Kjør med `--dry-run` for å se planlagte endringer uten å skrive filer.

Stiene til SQL filer i YAML-filen og CSV-mappene regnes fra mappen der konfigurasjonsfilen ligger. Å angi `--input-directory` velger CSV som kilde, og `--output-directory` velger CSV som mål; uten disse valgene brukes Oracle for input eller output, eller begge. Eksisterende resultatfiler overskrives på disk, oppførsel i databasen avhenger fra konfigurasjonen. 

Prikking er foreløpig deaktivert: resultatet får en boolsk `prikket`-kolonne med verdien `True`. R-integrasjonen er klargjort, men kjøres ikke ennå.

## Konfigurasjon

```yaml
connection:
  # prekonfigurerte verdier for host, port, and service_name
  database: DWHP
  schema: my_schema # Hvor i databasen resultatene skal lagres.
  # Fast streng:
  # user: my_username
  # Les fra miljøvariabel:
  # user: env://MY_USER_ENV_NAME
  # Les fra terminal prompt:
  # user: terminal://
  # Les fra Google Secret Manager:
  # user: gsm://projects/my_project/secrets/my_secret/versions/latest
  # A final path segment extracts a key from a flat JSON object:
  user: gsm://projects/my_project/secrets/my_secret/versions/latest/username
  # Passord må aldri lagres direkte i konfigurasjonsfilen:
  password: gsm://projects/my_project/secrets/my_secret/versions/latest/password
  
  timeout: 30 # optional, default

# Denne delen konfigurerer hva som skal gjøres
smale_aggregater:
  - navn: Lekmansspråk
    navn_en: Human readable name
    tabell: ost_TABELLNAVN_BESKRIVENDE
    innhold: >
       Dette er en innhold av småaggregater. Bakgrunn, begrensninger, osv...
    innhold_en: English description.
    # sti til SQL spørringen som definerer aggregatet
    sporring_sql: sporringer/ost_tabellnavn.sql
    periodisering: periode # kolonnen som angir tidsperiode
    # Dersom en periode er allerede lastet:
    # - overskriv_ikke: beholder eksisterende rader
    # - overskriv_alt: overskrive alle eksisterende rader
    # - overskriv_siste_periode: overskrive eksisterende rader for siste periode
    inkrementell: overskriv_alt
    tallkolonne:
      navn: Antall A
      kolonne: antall_a
      innhold: >
        Antall A måler blablabla

    # argumenter som sendes videre til R skriptet
    formula: "~ PERIODE * REGION * KJONN * ALDER"
    prikking: true
    saerskilt: false  

    variabler:
      - navn: Region
        navn_en: Region
        kolonne: region
        innhold: >
          Denne variablen beskriver regionen som antall_a gjelder for.
          
          I tilfellet av sammenslåing av regioner vil den inneholde dagens verdi. 
        innhold_en: English description.

      - navn: Periode
        navn_en: Period
        kolonne: periode
        innhold: >
          Denne variablen perioden som antall_a gjelder for på månedsgranularitet.

          Formatet er YYYYMM.
        innhold_en: English description.
```

Dersom man ikke spesifiserer noen av følgende felter, lastets verdiene inn fra Oracle kommentarer som må bruke tagging:
- navn: `#NAVN`
- navn_en: `#NAVN_EN`
- innhold: `#INNHOLD`
- innhold: `#INNHOLD_EN`

# Bruk av KI

Dette prosjektet bruker generativ KI for å generere kode.