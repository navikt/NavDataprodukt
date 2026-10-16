# Instruksjoner for Copilot

Dette prosjektet leverer Python-CLI-en `statistikkbank`; kommando- og feilmeldinger skal være på norsk. Følg `src/statistikkbank/PLAN.md` for domenekrav og arkitektur.


Kjør enhetstester sånn:
```sh
statistikkbank testenv pytest
```

Med argumenter:
```sh
statistikkbank testenv pytest -- -q
```

Oracle-testcontaineren må startes og stoppes utenfor sandkassen med `statistikkbank testenv setup` og `statistikkbank testenv teardown`. Ikke start Docker-containere direkte fra sandkassen.

SQL-filer leses relativt til YAML-konfigurasjonen. Ikke legg hemmeligheter i konfigurasjonsfiler, og ikke la standardkjøring endre databaseskjemaet.
