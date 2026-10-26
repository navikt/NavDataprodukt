# Instruksjoner for Copilot

Dette prosjektet leverer Python-CLI-en `statistikkprodukt`; kommando- og feilmeldinger skal være på norsk. Følg `src/statistikkprodukt/PLAN.md` for domenekrav og arkitektur.


Kjør enhetstester sånn:
```sh
uv run statistikkprodukt testenv pytest
```

Med argumenter:
```sh
uv run statistikkprodukt testenv pytest -- -q
```

Oracle-testcontaineren må startes og stoppes utenfor sandkassen med `statistikkprodukt testenv setup` og `statistikkprodukt testenv teardown`. Ikke start Docker-containere direkte fra sandkassen.

SQL-filer leses relativt til YAML-konfigurasjonen. Ikke legg hemmeligheter i konfigurasjonsfiler, og ikke la standardkjøring endre databaseskjemaet.
