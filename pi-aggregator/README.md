# pi-aggregator

Agrégateur de données du dashboard e-paper, hébergé sur le Raspberry Pi.
Remplace le Google Apps Script : il pré-agrège toutes les sources et expose
**un seul endpoint JSON** que l'ESP32 interroge à chaque réveil.

- `GET /dashboard` — JSON consolidé au [contrat attendu par le firmware](golden/README.md)
- `GET /healthz` — état du service et fraîcheur de chaque source

Les sources sont rafraîchies par une **tâche de fond** (cache « dernière bonne
valeur ») : la requête de l'ESP32 ne déclenche aucun appel réseau et répond
immédiatement, pour minimiser le temps éveillé.

## Sources (Phase 1)

| Clé JSON   | Source                              | Notes |
| ---------- | ----------------------------------- | ----- |
| `layout`   | `layout.json` local, relu à chaque requête | modifiable sans reflasher l'ESP32 |
| `weather`  | Open-Meteo (forme de `fetchOpenMeteo()`)   | sunrise/sunset sans secondes |
| `tracking` | PKGE `GET /v1/packages/list`        | omise si pas de clé API |
| `claude`   | Anthropic Usage Admin API (`usage_report/messages`, seaux 1d) | omise si pas de clé ; voir note ci-dessous |

### Note — widget « utilisation Claude » (squelette)

Nouvelle clé `claude` (hors contrat d'origine) : tokens entrée/sortie du **jour**
et des **7 derniers jours glissants** (UTC). Forme :

```json
{ "today": {"input_tokens": 0, "output_tokens": 0},
  "week":  {"input_tokens": 0, "output_tokens": 0} }
```

- Nécessite une **clé Admin Anthropic** (`sk-ant-admin...`) dans `[claude]` de
  `config.toml`. ⚠️ L'Admin API exige une **organisation Console** — elle n'est
  pas disponible pour un compte individuel. Sans clé, la clé JSON est omise.
- Le **widget firmware n'existe pas encore** : l'ID layout **1024** est réservé
  (`Active: false` dans `layout.json`, emplacement de l'ancien widget Stocks).
  À implémenter sur le gabarit `proxmox.cpp`, puis passer `Active` à `true`.
- Si la source de données change un jour (autre API, données locales Claude
  Code), seule `fetch_claude_usage()` est à remplacer — la forme JSON est stable.

`stocks`, `makerworld`, `proxmox` : supprimés. `calEvents` : reporté.
Bambu Lab reste en MQTT direct depuis l'ESP32 (hors contrat HTTP).
Une clé absente est tolérée par le firmware (widget « Not available »).

## Installation (Pi ou local)

```bash
cd pi-aggregator
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp config.example.toml config.toml   # puis adapter (coordonnées, clé PKGE)
```

`config.toml` est gitignoré (il contient la clé API PKGE).

## Lancer

```bash
uvicorn --factory pi_aggregator.app:create_app --host 0.0.0.0 --port 8080
# ou : python -m pi_aggregator.app
```

Vérification rapide : `curl http://localhost:8080/dashboard | python3 -m json.tool`

## Tests & lint

```bash
ruff check .
pytest
```

Les tests valident la forme produite contre `golden/dashboard.json`
(clés `Row_Height`/`Col_Width`, littéraux de statut, formats de date,
limites firmware, payload < 60 Ko) sans aucun appel réseau.
