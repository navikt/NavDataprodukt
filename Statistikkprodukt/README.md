# Statistikkprodukt

`statistikkprodukt` er et verktøy for datateam for å lage statistikkaggregater med Gaussian Suppression prikking/maskering av små verdier for personvernhensyn.

Verktøyet konfigureres med yaml filer og kan håndtere flere aggregater samtidig.

For hver aggregat::
- Lese data fra Oracle/CSV inkrementell
- Kjøre Gaussian Suppression algoritme implementert i R for hver 
- Lagre resultatet i Oracle/CSV
- Les metadata fra en bredt aggregat tabell (obt), oppdater fra konfigurasjonsfilen, skriv som databasekommentarer-

For hver aggregat lages to resultattabeller: `{tabell}_prepub` med de prikkede dataene, og `{tabell}_kontroll` med kontrolldata for feilsøking.

Denne filen er brukerdokumentasjon. [README_DEV.md](README_DEV.md) er utviklerhåndbok.

## Kom i gang

Last ned repositoriet og installer python avhengigheter:
```sh
uv sync
uv run statistikkprodukt --help
```

KNAST har allerede R installert. For å installere eller oppdatere R avhengighetene for prikking, kjør:
```sh
uv run statistikkprodukt installer-r-pakker
```

Kjør eksempelet, som leser to CSV-filer fra `eksempel/data_inn` og skriver resultatene til `eksempel/data_ut`, uten Oracle-tilkobling eller hemmeligheter:

```sh
cd Statistikkprodukt/eksempel
uv run statistikkprodukt last \
  --config konfigurasjon.yml \
  --kilde=csv \
  --maal=csv
```

Konfigurasjonsmuligheter:
- `--dry-run` viser planlagte endringer uten å modifisere data.
- `--kilde`/`--maal` er enten `db` (default) eller `csv`
- `--kilde-mappe`/`--maal-mappe` angir mappene for CSV-filer (default: `data_inn` og `data_ut`)

Det betyr man kan:
- Skrive fra Oracle til Oracle, normal ETL.
- Skrive fra CSV-filer til CSV-filer, uten Oracle-tilkobling, bra for testing.
- Skrive fra Oracle til CSV-filer, bra for testing.
- Skrive fra CSV-filer til Oracle, for eventuell manuell overstyring.

Som standard skrives alle små aggregater. Enkelte kan utvelges med navn:
```shell
uv run statistikkprodukt last --config konfigurasjon.yml ost_befolkning_alder ost_befolkning_kjonn
```

## Databaseskjema 
Databasetabeller kan opprettes som følger:

```sh
# For alle aggregater i konfigurasjonen
uv run statistikkprodukt skjema opprett --config konfigurasjon.yml

# For enkelte aggregater
uv run statistikkprodukt skjema opprett --config konfigurasjon.yml ost_2 ost_1
```

Det opprettes to tabeller per aggregat.
```sql
create table ost_1_kontroll (
  periode_kolonne varchar2(10),
  variabel_kolonne varchar2(10),
  -- tall som ikke er prikket
  tall_kolonne number,
  -- primærprikking (små tall) 1/0 for ja/nei
  primary number, 
  -- sekundærprikking via gaussian suppression 1/0 for ja/nei
  suppressed number
);

create table ost_1_prepub (
  periode_kolonne varchar2(10),
  variabel_kolonne varchar2(10),
  -- null når det er prikket
  tall_kolonne number
);
```

## Konfigurasjon

### Hovedkonfigurasjonsfil
Konfigurasjonen er delt i én felles fil og én YAML-fil per småaggregat. Den felles filen inneholder databasetilkobling, søkemønstre for aggregatfilene og navnene på aggregatene som skal kjøres. Lag ulike filer for ulike miljøer

```yaml
connection:
  # Velg enten en profil ...
  database: DWHP
  # ... eller oppgi alle verdiene direkte i stedet:
  # host: oracle.example.no
  # port: 1521
  # service: ORCL
  schema: mitt_skjemanavn
  # Bruker kan oppgis direkte eller hentes fra en støttet hemmelighetskilde.
  user: gsm://projects/my_project/secrets/my_secret/versions/latest/username
  password: gsm://projects/my_project/secrets/my_secret/versions/latest/password
  timeout: 30

# Hvor i repositoriet aggregatkonfigurasjonen finnes
mapper:
  - aggregater/**

# Hvilke aggregater som skal kjøres. Navnene må samsvare med YAML-filene i `mapper`.
smale_aggregater:
  - ost_befolkning_alder
  - ost_befolkning_kjonn
```

Mer om lasting av hemmeligheter følger.

## Konfigurasjon per småaggregat

Per småaggregat må det lages:
- `{aggregatnavn}.yml` som konfigurasjon
- `{aggregatnavn}.sql` som SQL-spørring for å hente data fra OBT-tabellen.


Eksempel på aggregatfil:

```yaml
definisjon:
  # Metadata per småaggregat, påkrevd
  navn: "Kort navn på norsk"
  navn_en: "Short name in English"
  innhold: "Beskrivelse av innhold på norsk"
  innhold_en: "Description of content in English"
  
  # Konfigurasjon av aggregat
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

`obt_tabell` er OBT-tabellen som er datagrunnlaget og leverer metadata.

Metadata på variabler og tallkolonne kommer fra kolonnekommentarer med tags:
- `#NAVN` for norsk navn
- `#NAVN_EN` for engelsk navn
- `#INNHOLD` for norsk beskrivelse
- `#INNHOLD_EN` for engelsk beskrivelse

De kan overskrives med:
```yaml
# ...
  tallkolonne:
    kolonne: antall
    navn: "Navn på norsk"
    navn_en: "Name in English"
    innhold: "Beskrivelse på norsk"
    innhold_en: "Description in English"
  variabler:
    - kolonne: periode
      navn: "Navn på norsk"
      # ...
```

### Inkrementelle laster

Følgende inkrementelle strategier er støttet. Inkrementelle laster baserer seg på periodekolonnen.

#### `overskriv_ikke`

Laster kun nye perioder:
```text
# I kilden
202501
202502
202503

# I målet
202502

# Lastet
202501
202503
```

#### `overskriv_alt`

Overskrive alle perioder som finnes i kilden. Perioder som ikke finnes i kilden, men som finnes i målet, beholdes.

```text
# I kilden
202501
202502
202503

# I målet
202412
202502

# Lastet
202501
202501
202503

# Perioden 202412 beholdes.
```

#### `overskriv_siste_periode`

Som `overskriv_ikke`, men den nyeste perioden i målet overskrives. 

```text
# I kilden
202412
202501
202502
202503

# I målet
202501
202502

# Lastet
202412
202502
202503
```

### Hemmeligheter

Hemmeligheter kan lastes fra Google Secret Manager (GSM), miljøvariabler eller terminalen (lokal utvikling).

NB at passordet _må_ være en hemmelighetsreferanse, der er ikke mulig å legge inn passord i klartekst.

#### GSM

```yaml
  user: gsm://projects/my_project/secrets/my_secret/versions/latest/username
  password: gsm://projects/my_project/secrets/my_secret/versions/latest/password
```
Leser fra hemmeligheten `my_secret` i prosjektet `my_project`. Det forventes at den inneholder en JSON-string, og den pakkes ut med nøklene `username` og `password`. De kan velges fritt. 

Nøklene er valgfritt, man kan også bruke hele hemmeligheten som en enkel verdi:
```yaml
  user: my_user
  password: gsm://projects/my_project/secrets/my_secret/versions/latest
```

#### Miljøvariabler

```yaml
  user: env://DB_USER
  password: env://DB_PASSWORD
```

#### Lokal utvikling

Lag deg en egen fil til lokal utvikling, ikke sjekk den inn i versjonskontroll.

```yaml
  user: my_ident
  password: terminal://
```

Da leses hemmeligheten fra terminalen.

Vi jobber på å få integrasjon med KNAST sin `dvh` kommandoen for å slippe å taste passord ved hver kjøring.


# Bruk av KI

Dette prosjektet bruker generativ KI for å generere kode.