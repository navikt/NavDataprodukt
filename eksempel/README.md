# Lokalt eksempel

Dette eksemplet kjører hele dataflyten lokalt uten Oracle eller tilgang til hemmeligheter. `inputs/` inneholder de to kildedatafilene. Resultatene i `outputs/` viser forventet format fra den nåværende mocken for prikking.

Fra prosjektroten kjører du:

```sh
uv run statistikkbank aggregat prikking \
  --config eksempel/konfigurasjon.yml \
  --input-format csv --input-directory inputs \
  --output-format csv --output-directory outputs
```

Begge katalogstiene regnes relativt til konfigurasjonsfilen. Eksisterende resultatfiler overskrives fordi eksempelets aggregater bruker `overskriv_alt`. For å se planlagte endringer uten å skrive filer:

```sh
uv run statistikkbank aggregat prikking --dry-run \
  --config eksempel/konfigurasjon.yml \
  --input-format csv --input-directory inputs \
  --output-format csv --output-directory outputs
```

SQL-filene peker på OBT-kildetabeller, men brukes ikke når `--input-format=csv` er valgt. Bytt til databaseinnlesing når Oracle-profil, nettverk og hemmelighetsvariabler er konfigurert.
