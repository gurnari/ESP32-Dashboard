# Widget « charge du Pi » (CPU / RAM / température)

> Design validé le 2026-06-29. Branche : `feat/pi-load-widget`.

## Objectif

Afficher l'état de santé du Raspberry Pi qui héberge l'agrégateur : **% CPU**,
**% RAM** et **température CPU**. Le Pi lit ses **propres** métriques et les expose
dans le JSON consolidé ; l'ESP32 parse et dessine, sans requête supplémentaire.

## Flux de données — passe par le contrat JSON

Contrairement au DHT11 (capteur local hors contrat, cf
[[migration-decisions]] PR #10), le Pi-load **entre dans le contrat JSON** : nouvelle
clé de 1er niveau `piload`. Modèle = la source `claude_usage` (le Pi calcule, expose
une clé, le firmware parse). `proxmox.cpp` sert de gabarit **uniquement pour le rendu**
du widget — **pas** pour le fetch (proxmox fait son propre HTTPS depuis l'ESP, ce que
ce fork supprime ; ici la donnée arrive dans la requête unique vers le Pi).

Forme produite :
```json
"piload": {"cpu": 12.5, "ram": 41.0, "temp": 48.3}
```
- `cpu`, `ram` : pourcentages 0–100, float arrondi à 1 décimale.
- `temp` : °C, float 1 décimale. **Omise** si illisible (voir ci-dessous).

## Décisions actées (choix utilisateur)

- Métriques affichées : **CPU %, RAM %, Température** (pas de load average).
- Température illisible (Mac de dev, runner CI sans `/sys/class/thermal`) →
  **champ `temp` omis** du JSON ; cpu/ram restent valides. Le firmware n'affiche
  alors pas la ligne Temp.
- Rendu **texte seul** (3 lignes), calqué sur `proxmox.cpp`. Pas de barres.
- Place à l'écran : **remplace Cal Events (ID 2)**. ID 2 passe `Active: false` ;
  nouveau widget **ID 4096** à sa position. Le grand Calendar (ID 256) reste.

## Composants

### 1. Source Pi — `pi-aggregator/pi_aggregator/sources/piload.py` (nouveau)

Sans dépendance (le Pi est Linux ; lecture `/proc` + `/sys`). Fonctions de parsing
**pures** (entrée = texte, sortie = nombre) pour des tests déterministes :

- `parse_cpu_percent(stat_before: str, stat_after: str) -> float`
  - Parse la ligne `cpu ` de `/proc/stat` (jiffies). `% = 100 * (Δbusy / Δtotal)`
    où `total = somme des champs`, `idle = idle + iowait`, `busy = total - idle`.
  - Δtotal == 0 → renvoie 0.0 (pas de division par zéro).
- `parse_mem_percent(meminfo: str) -> float`
  - `MemTotal` et `MemAvailable` de `/proc/meminfo` (kB).
  - `% = 100 * (MemTotal - MemAvailable) / MemTotal`. MemTotal == 0 → 0.0.
- `read_temp_c(thermal_raw: str) -> float`
  - `/sys/class/thermal/thermal_zone0/temp` en millidegrés → `float / 1000`.

- `async def fetch_piload() -> dict | None`
  - Lit `/proc/stat`, `await asyncio.sleep(0.3)`, relit `/proc/stat` → `cpu`.
  - Lit `/proc/meminfo` → `ram`.
  - Tente `/sys/class/thermal/thermal_zone0/temp` → `temp` ; en cas d'absence /
    d'erreur de lecture, **n'ajoute pas** la clé `temp`.
  - Si `/proc/stat` ou `/proc/meminfo` est illisible (plateforme non-Linux) →
    renvoie `None` (clé `piload` omise, widget « Not available »).
  - Valeurs `cpu`/`ram` arrondies à 1 décimale ; `temp` à 1 décimale.

### 2. Configuration — `pi-aggregator/pi_aggregator/config.py` + `config.example.toml`

- Nouvelle dataclass `PiLoadConfig(enabled: bool = True, refresh_minutes: int = 1)`.
- `Config` gagne `piload: PiLoadConfig | None = None`.
- `load_config` : lit `[piload]` ; `piload = PiLoadConfig(**raw)` seulement si
  présent **et** `enabled` vrai, sinon `None` (même logique de gate que les autres).
- `config.example.toml` : ajouter
  ```toml
  [piload]
  enabled = true
  # refresh_minutes = 1
  ```

### 3. Agrégateur — `pi-aggregator/pi_aggregator/aggregator.py`

- Importer `fetch_piload`.
- Dans `Aggregator.__init__`, après les autres sources :
  ```python
  if cfg.piload:
      self.sources.append(
          Source("piload", fetch_piload, timedelta(minutes=cfg.piload.refresh_minutes))
      )
  ```
- `fetch_piload` ne prend ni config ni client (lecture locale) → l'adapter en
  `lambda: fetch_piload()` pour respecter la signature `Callable[[], Awaitable]`.
- `build()` émet déjà `doc["piload"]` automatiquement si la valeur n'est pas None.

### 4. Firmware — `firmware/piload.cpp` + `firmware/piload.h` (nouveaux)

- `struct PiLoadData { float cpu; float ram; float temp; bool hasTemp; bool valid; };`
  + `extern PiLoadData piload;`
- `void parsePiLoad(JsonVariantConst obj);` — remplit `piload` depuis `doc["piload"]` :
  `valid = !obj.isNull()` ; `cpu = obj["cpu"] | 0.0f` ; `ram = obj["ram"] | 0.0f` ;
  détection de la temp en **ArduinoJson v7** via `obj["temp"].is<float>()`
  (le projet est en v7 ; `containsKey` y est déprécié) → `hasTemp` ;
  `temp = obj["temp"] | 0.0f`. Appel côté `fetchData()` :
  `parsePiLoad(doc["piload"]);` (un `JsonVariantConst` se construit depuis le
  sous-document, pas besoin de cast explicite).
- `void drawPiLoad(LayoutItem* item);` — gabarit rendu `proxmox.cpp` :
  - `!piload.valid` → message indisponible (lignes inline « Not available » /
    « at the moment », comme `drawAmbient`, le helper `drawUnavailableMessage` étant
    `static` dans fetchAllInfo.cpp).
  - sinon 3 lignes via `drawSparseString(&epaperFont, …)` :
    `"CPU  %.0f %%"`, `"RAM  %.0f %%"`, et si `hasTemp` `"Temp %.0f°C"` (icône
    thermomètre `drawSparseChar(&MDI_22_Sparse, …, 0xF050F, …)` optionnelle).
    Si `!hasTemp`, ne pas dessiner la 3e ligne.

### 5. Parsing dans la requête unique — `firmware/fetchAllInfo.cpp`

- Dans `fetchData()`, là où les autres clés de 1er niveau sont parsées (weather,
  tracking…), appeler `parsePiLoad(doc["piload"]);` (inclure `piload.h`).

### 6. Dispatch — `firmware/firmware.ino`

- `#include "piload.h"`.
- Récupérer `LayoutItem* infoPiLoad = getLayout(4096);` aux **trois** sites
  `getLayout` (démo, chemin principal, re-fetch post-`fetchData()`).
- Drapeau `bool piloadIf = infoPiLoad && infoPiLoad->Active;`
  **recalculé après le re-fetch** (leçon PR #10 : sinon `piloadIf` périmé →
  null-deref si le pointeur change au 1er boot).
- Rendu plein écran : `if (piloadIf) drawPiLoad(infoPiLoad);`
- Rendu partiel : `if (piloadIf) updatePartial(infoPiLoad, drawPiLoad);`
- Mode démo : ajouter `infoPiLoad` à `items[]`/`labels[]` (« PiLoad »), borne 10→11
  (le widget Ambient l'avait déjà passée de 9 à 10) — vérifier l'égalité des deux
  tableaux et de la borne.

### 7. Layout — `pi-aggregator/layout.json`

- ID 2 « Cal Events » : `Active` passe à `false` (entrée conservée, dormante).
- Nouvelle entrée **ID 4096 « PiLoad »** : `Active: true`, `PosX: 440, PosY: 255,
  Width: 360, Height: 145`, `Row_Height: 40, Col_Width: 0, Refresh: 1, Group: 6`,
  tous les `Extra*` vides. Mêmes clés/ordre + orthographe underscore que les autres.

## Ce qui ne change PAS

- Le firmware fait toujours **une seule requête** vers le Pi.
- Pas de fetch HTTPS direct depuis l'ESP (≠ proxmox d'origine) ; pas de MQTT.
- Aucune nouvelle dépendance Python (lecture `/proc`+`/sys`) ni firmware.
- Flux Bambu/MQTT, météo, tracking, ambient inchangés.

## Tests & vérification

- **Pi (TDD)** : tests unitaires des fonctions pures `parse_cpu_percent`,
  `parse_mem_percent`, `read_temp_c` avec échantillons de texte figés (dont les cas
  Δtotal==0, MemTotal==0, temp absente). Test de contrat : ID 4096 présent/`Active`,
  ID 2 inactif ; `len(layout) <= 15` et clés conformes restent verts. `Config()` sans
  `[piload]` → source absente, dashboard déterministe. `pytest` + `ruff` verts.
- **Firmware** : compilation `--profile xiao_esp32c6 .` (cible, gate liant) ; non-
  régression esp32 avec flags partition (cf [[migration-decisions]] : le profil esp32
  nu déborde, c'est attendu).
- **Validation réelle** (par le propriétaire, sur le Pi) : `curl /dashboard` montre
  `piload` avec `temp` ; widget affiché à la place de Cal Events.

## Pièges connus

- `piloadIf` à recalculer après le re-fetch (cf PR #10).
- ID **4096** = prochain bitmask libre (512 = MakerWorld supprimé, interdit par
  `tests/test_contract.py` ; 1024 = Claude inactif ; 2048 = Ambient).
- `fetch_piload` n'a pas la signature `(cfg, client)` des autres fetchers → wrapper
  `lambda: fetch_piload()` dans l'agrégateur.
- Sur CI Linux, `/proc` existe → si un test intègre la vraie source, `piload`
  apparaîtra ; garder la source **hors** des tests de contrat déterministes (via
  `Config()` sans `[piload]`).
- **Widget réseau ≠ capteur local** (corrigé en revue finale) : `piload` n'est
  peuplé que dans `fetchData()`, qui ne tourne pas à chaque réveil. Il faut donc
  le traiter comme les widgets réseau (météo/tracking/**makerworld**), PAS comme
  Ambient/DHT11 : **persister en Preferences** après le parse (`savePiLoad()`) et
  **recharger au rendu** (`loadPiLoad()` en tête de `drawPiLoad`), et gater le
  redraw avec `shouldFetchRefresh(infoPiLoad)` (pas `Active` direct) avec un
  `Refresh` raisonnable (15, pas 1). Sinon : « Not available » + scintillement à
  chaque réveil sans fetch. Ne pas recopier le gabarit d'activation d'Ambient.
