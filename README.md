# Statistikkbank

`statistikkbank` lager små statistikkaggregater og markerer rader som er behandlet av prikking. Verktøyet kan hente data fra Oracle eller lokale CSV-filer og lagre resultatet i Oracle eller CSV.

## Kom i gang

Installer Python 3.14 eller nyere, R og pakkene fra prosjektet:

```sh
uv sync
uv run statistikkbank --help
```

Lag en YAML-konfigurasjonsfil med tilkobling og aggregater. Passord må hentes fra en hemmelighetsreferanse; ikke skriv passord direkte i filen. Se `eksempel/` for en kjørbar lokal CSV-konfigurasjon.

Eksemplet leser to CSV-filer fra `eksempel/inputs/` og skriver resultatene til `eksempel/outputs/`, uten Oracle-tilkobling eller hemmeligheter:

```sh
uv run statistikkbank aggregat prikking --config eksempel/konfigurasjon.yml \
  --input-format csv --input-directory inputs/ \
  --output-format csv --output-directory outputs/
```

Kjør med `--dry-run` for å se planlagte endringer uten å skrive filer:

```sh
uv run statistikkbank aggregat prikking --dry-run \
  --config eksempel/konfigurasjon.yml \
  --input-format csv --input-directory inputs/ \
  --output-format csv --output-directory outputs/
```

Relativ sti i YAML-filen og CSV-mappene regnes fra mappen der konfigurasjonsfilen ligger. Eksemplets eksisterende resultatfiler overskrives fordi aggregatene bruker `overskriv_alt`. SQL-filene peker på OBT-kildetabeller, men brukes ikke ved CSV-innlesing. Bytt til databaseinnlesing når Oracle-profil, nettverk og hemmelighetsvariabler er konfigurert.

Prikking er foreløpig deaktivert: resultatet får en boolsk `prikket`-kolonne med verdien `True`. R-integrasjonen er klargjort, men kjøres ikke ennå.

## Oracle-miljø

Kommandoer som bruker Oracle, trenger nettverkstilgang og riktige hemmeligheter. Databaseprofilenes vertsnavn og tjenester er foreløpige plassholdere og må oppdateres før bruk mot reelle miljøer.
