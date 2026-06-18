# Dashboard e-paper ESP32 — monorepo

Fork personnel de `VoIPshare/ESP32-eInk-Dashboard`. Objectif : supprimer la
dépendance au Google Apps Script et déporter toute l'agrégation de données sur un
Raspberry Pi du réseau local, en réutilisant le code de rendu firmware existant.

L'ESP32 se réveille, fait **une seule requête HTTP** vers le Pi, parse un JSON
consolidé, dessine les widgets e-paper, puis se rendort (deep sleep).

📘 **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — documentation de référence
complète : fonctionnement détaillé firmware + Pi, contrat JSON, build/flash,
déploiement, dépannage et état d'avancement. À lire pour reprendre le projet à la main.

## Structure

| Dossier            | Rôle                                                                 |
| ------------------ | ------------------------------------------------------------------- |
| [`firmware/`](firmware/) | Firmware C++/Arduino (XIAO ESP32C6 + e-paper 7,5"). Voir [firmware/README.md](firmware/README.md). |
| [`pi-aggregator/`](pi-aggregator/) | Agrégateur Python sur le Raspberry Pi : expose `GET /dashboard` au format JSON attendu par le firmware. |
| [`pi-aggregator/golden/`](pi-aggregator/golden/) | Fixture JSON de référence (contrat à respecter côté Pi). |
| [`googleScripts/`](googleScripts/) | Ancien Apps Script + CSV — **référence/legacy** ayant servi à reconstituer le contrat JSON. À ne pas réintroduire. |

## Contrat JSON

Le firmware (`firmware/fetchAllInfo.cpp::fetchData()`) reste la **référence** du
contrat. Le Pi doit produire le même schéma pour réutiliser le parsing/rendu sans
modification. Le contrat exact et ses pièges sont documentés dans
[pi-aggregator/golden/README.md](pi-aggregator/golden/README.md).

## Build

- **Firmware** : profils `arduino-cli` dans [`firmware/sketch.yaml`](firmware/sketch.yaml).
  Depuis `firmware/` : `arduino-cli compile --profile <profil> .`
- **Pi** : voir [pi-aggregator/README.md](pi-aggregator/README.md) — `ruff check . && pytest`
  puis `uvicorn --factory pi_aggregator.app:create_app`.
