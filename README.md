# Dashboard e-paper ESP32 — monorepo

Fork personnel de `VoIPshare/ESP32-eInk-Dashboard`. Objectif : supprimer la
dépendance au Google Apps Script et déporter toute l'agrégation de données sur un
Raspberry Pi du réseau local, en réutilisant le code de rendu firmware existant.

L'ESP32 se réveille, fait **une seule requête HTTP** vers le Pi, parse un JSON
consolidé, dessine les widgets e-paper, puis se rendort (deep sleep).

📘 **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — documentation de référence
complète : fonctionnement détaillé firmware + Pi, contrat JSON, build/flash,
déploiement, dépannage et état d'avancement. À lire pour reprendre le projet à la main.

## Services & disposition de l'écran

9 widgets (8 actifs). Selon l'origine de la donnée : 🟢 calculée **localement sur
l'ESP32**, 🔵 servie **par le Pi** dans la requête unique, 🟣 **MQTT direct**.

| Widget (ID) | Donnée | Origine |
| --- | --- | --- |
| Horloge / Date (1) | heure + date | 🟢 ESP32 — NTP |
| Batterie (128) | niveau batterie | 🟢 ESP32 — pont diviseur sur A0 |
| Calendrier du mois (256) | grille du mois, jour entouré (sans événements) | 🟢 ESP32 — NTP |
| Ambiant (2048) | température + humidité | 🟢 ESP32 — DHT11 sur D6 |
| Météo (8) | prévisions | 🔵 Pi — source Open-Meteo |
| Suivi colis (16) | statut colis | 🔵 Pi — source PKGE (clé requise) |
| Charge du Pi (4096) | CPU / RAM / température | 🔵 Pi — lecture `/proc` + `/sys` |
| Bambu Lab (64) | statut imprimante 3D | 🟣 MQTT direct depuis l'ESP |
| ~~Cal Events~~ (2) | agenda 24 h | ⚫ désactivé (remplacé par Charge du Pi) |

Supprimés : Stocks, MakerWorld, Proxmox, Google Calendar (events), Claude, Zigbee.
Reporté : Apple Music (Last.fm).

Disposition à l'écran (800×480, deux colonnes scindées à x=440) :

```
        COLONNE GAUCHE (x 10–440)          COLONNE DROITE (x 440–800)
   y0 ┌───────────────────────────┐  y0 ┌───────────────────────────┐
      │  Horloge / Date     (1)   │     │  Batterie         (128)   │ y28
      │  🟢 NTP local      430×155│     ├───────────────────────────┤
      │                           │     │  Calendrier du mois (256) │
  y155├───────────────────────────┤     │  🟢 NTP local             │
      │  Ambiant  T° / H%  (2048) │     │  (jour entouré, sans      │
      │  🟢 DHT11 local    430×130│     │   événements)      360×230│
  y285├───────────────────────────┤ y255├───────────────────────────┤
      │  Météo (Open-Meteo)  (8)  │     │  Charge du Pi     (4096)  │
      │  🔵 ← Pi           430×105│     │  CPU / RAM / Temp  🔵 ← Pi │
  y390├───────────────────────────┤     │                    360×145│
      │  Bambu Lab          (64)  │ y400├───────────────────────────┤
      │  🟣 MQTT direct    430×90 │     │  Suivi colis (16)  🔵 ← Pi│
  y480└───────────────────────────┘ y480└───────────────────────────┘
```

La disposition est servie par le Pi (`pi-aggregator/layout.json`) : modifiable
sans reflasher l'ESP32.

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
