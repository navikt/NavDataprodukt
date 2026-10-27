# Statistikkprodukt

`statistikkprodukt` lager små statistikkaggregater og markerer rader som er behandlet av prikking. Verktøyet kan hente data fra Oracle eller lokale CSV-filer og lagre resultatet i Oracle eller CSV.

Denne filen er brukerdokumentasjon. [README_DEV.md](README_DEV.md) er utviklerhåndbok.

## Kom i gang

Installer Python 3.12 eller nyere, R og pakkene fra prosjektet:

```sh
uv sync
uv run statistikkprodukt --help
```

Kjør eksempelet, som leser to CSV-filer fra `eksempel/inputs/` og skriver resultatene til `eksempel/outputs/`, uten Oracle-tilkobling eller hemmeligheter:

```sh
uv run statistikkprodukt last \
  --config eksempel/konfigurasjon.yml \
  --input-directory inputs/ \
  --output-directory outputs/
```

Kjør med `--dry-run` for å se planlagte endringer uten å skrive filer.

`--input-directory` velger CSV som kilde, og `--output-directory` velger CSV som mål. Uten disse valgene leses data fra eller skrives til Oracle. Eksisterende resultatfiler overskrives. Et tomt resultat endrer ikke dataradene i Oracle, men kolonnekommentarene synkroniseres ved databaseskriving.

Opprett en tom måltabell basert på SQL-spørringen og skriv DDL med kolonnekommentarer til standard output:

```sh
# For alle aggregater i konfigurasjonen
uv run statistikkprodukt skjema opprett --config eksempel/konfigurasjon.yml

# For enkelte aggregater
uv run statistikkprodukt skjema opprett --config eksempel/konfigurasjon.yml aggregat1 aggregat2
```

Kommandoen bruker den konfigurerte Oracle-tilkoblingen til å sjekke målskjemaet og hente metadata. Tabeller som finnes fra før, hoppes over. Legg til `--db` for å utføre DDL-en i Oracle i stedet for å skrive den ut. Tabellen opprettes uten rader ved hjelp av `WHERE 1 = 0`.

Prikking er foreløpig ikke implementert: resultatet får en boolsk `prikket`-kolonne med verdien `True`. R-integrasjonen er klargjort, men kjøres ikke ennå.

## Konfigurasjon

Konfigurasjonen er delt i én felles fil og én YAML-fil per småaggregat. Den felles filen inneholder databasetilkobling, søkemønstre for aggregatfilene og navnene på aggregatene som skal kjøres:

```yaml
connection:
  # Velger forhåndsdefinerte verdier for vert, port og tjenestenavn.
  database: DWHP
  schema: mitt_skjemanavn
  # Bruker kan oppgis direkte eller hentes fra en støttet hemmelighetskilde.
  user: gsm://projects/my_project/secrets/my_secret/versions/latest/username
  password: gsm://projects/my_project/secrets/my_secret/versions/latest/password
  timeout: 30

mapper:
  - aggregater/**

smale_aggregater:
  - ost_befolkning_alder
  - ost_befolkning_kjonn
```

Hvert navn i `smale_aggregater` må finnes blant YAML-filene som treffes av `mapper`. Hver aggregatfil inneholder én definisjon under `definisjon`. Filnavnet bestemmer måltabellen (`tabell`) og navnet på SQL-filen: `sporringer/ost_befolkning_alder.yml` gir tabellen `ost_befolkning_alder` og SQL-filen `sporringer/ost_befolkning_alder.sql`. Ikke angi `tabell` eller `sporring_sql` i aggregatfilen.

Eksempel på aggregatfil:

```yaml
definisjon:
  obt_tabell: befolkning
  periodisering: periode  # kolonnenavn for periodisering
  inkrementell: overskriv_alt  # overskriv_ikke, overskriv_alt, overskriv_siste_periode
  tallkolonne:
    kolonne: antall
  formula: "~ periode * alder"
  prikking: true
  saerskilt: false
  variabler:
    - kolonne: periode
    - kolonne: alder
```

`obt_tabell` angir OBT-tabellen som er datagrunnlaget som det smale aggregatet bygges fra i SQL spørringen. Den brukes når metadata mangler i YAML-filen. Den kan oppgis som `SKJEMA.TABELL`; uten skjema brukes verdien fra `connection.schema`. Metadatafeltene `navn`, `navn_en`, `innhold` og `innhold_en` er valgfrie når de finnes i databasekommentarene. Kommentarene må bruke taggene `#NAVN`, `#NAVN_EN`, `#INNHOLD` og `#INNHOLD_EN`. Metadata er ikke nødvendig når både input og output er lokale CSV-filer.

`password` må være en hemmelighetsreferanse, ikke et passord i klartekst. Støttede former er `env://VARIABEL`, `terminal://` og `gsm://projects/.../secrets/.../versions/...`; for GSM kan siste stisegment angi en nøkkel i en flat JSON-verdi. `terminal://` virker bare når programmet kjøres fra en terminal.

`inkrementell` kan være `overskriv_ikke` (legg til perioder som ikke finnes), `overskriv_alt` (erstatt alle perioder) eller `overskriv_siste_periode` (erstatt siste periode i resultatet). Bruk `--dry-run` for å se hva kjøringen vil gjøre uten å skrive til databasen eller CSV-filer.

# Bruk av KI

Dette prosjektet bruker generativ KI for å generere kode.