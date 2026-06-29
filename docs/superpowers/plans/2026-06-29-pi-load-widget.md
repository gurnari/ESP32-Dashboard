# Widget charge du Pi — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Afficher l'état de santé du Raspberry Pi (CPU %, RAM %, température) dans un widget e-paper, alimenté par une nouvelle clé `piload` du JSON consolidé.

**Architecture:** Le Pi lit ses propres métriques via `/proc` et `/sys` (sans dépendance), les expose dans une clé `piload` (modèle source `claude_usage`). L'ESP32 parse cette clé dans sa requête unique et dessine un widget texte (ID 4096) à la place de Cal Events (ID 2). Aucun fetch HTTP supplémentaire.

**Tech Stack:** Python (FastAPI/asyncio, lecture `/proc`+`/sys`), pytest/ruff. Firmware C++/Arduino (ArduinoJson v7, GxEPD2), arduino-cli.

## Global Constraints

- Spec de référence : `docs/superpowers/specs/2026-06-29-pi-load-widget-design.md`.
- Clé JSON : `"piload": {"cpu": <float>, "ram": <float>, "temp": <float>}` ; `cpu`/`ram` en % 0–100 arrondis à 1 décimale ; `temp` en °C 1 décimale, **omise si illisible**.
- **Aucune nouvelle dépendance** (Python : `/proc`+`/sys` ; firmware : aucune lib).
- Widget **ID 4096** (prochain bitmask libre ; 512 interdit, 1024 Claude inactif, 2048 Ambient).
- ID 2 « Cal Events » passe `Active: false` ; le widget PiLoad prend sa position (PosX 440, PosY 255, Width 360, Height 145).
- Le firmware ne fait **qu'une seule requête** vers le Pi ; pas de fetch direct depuis l'ESP.
- ArduinoJson **v7** : détecter la présence d'un champ via `.is<float>()` / `.is<JsonObject>()`, jamais `containsKey` (déprécié).
- `piloadIf` (firmware) **recalculé après le re-fetch** du layout post-`fetchData()` (leçon PR #10 : sinon null-deref au 1er boot).
- Gate Pi = `python -m pytest -q` + `ruff check .` (depuis `pi-aggregator/`, venv `.venv`).
- Gate firmware = compilation (pas de tests unitaires firmware). Profil XIAO liant :
  - `arduino-cli compile --profile xiao_esp32c6 .` (depuis `firmware/`).
  - Non-régression esp32 (le profil nu déborde, attendu) : `FW=$(pwd); arduino-cli compile --profile esp32 --board-options PartitionScheme=custom --build-property "build.custom_partitions=$FW/partitions.csv" --build-property "upload.maximum_size=3604480" .`
- Commits atomiques, conventionnels, en français. **Aucune mention Claude Code / IA.**
- Tout l'affichage utilisateur en français (sauf « Not available »/« at the moment » conservés pour rester cohérents avec les autres widgets).

---

### Task 1 : Source Pi `piload.py` (TDD)

**Files:**
- Create: `pi-aggregator/pi_aggregator/sources/piload.py`
- Test: `pi-aggregator/tests/test_piload.py`

**Interfaces:**
- Consumes : rien (stdlib + asyncio).
- Produces :
  - `parse_cpu_percent(stat_before: str, stat_after: str) -> float`
  - `parse_mem_percent(meminfo: str) -> float`
  - `read_temp_c(thermal_raw: str) -> float`
  - `async def fetch_piload() -> dict | None` → `{"cpu": float, "ram": float[, "temp": float]}` ou `None`.

- [ ] **Step 1 : Écrire les tests des fonctions pures (échouent)**

`pi-aggregator/tests/test_piload.py` :
```python
import asyncio

from pi_aggregator.sources.piload import (
    fetch_piload,
    parse_cpu_percent,
    parse_mem_percent,
    read_temp_c,
)

STAT_BEFORE = "cpu  100 0 100 700 100 0 0 0 0 0\ncpu0 50 0 50 350 50 0 0 0 0 0\n"
STAT_AFTER = "cpu  150 0 150 900 100 0 0 0 0 0\ncpu0 75 0 75 450 50 0 0 0 0 0\n"
# before: total=1000 idle_all=800 busy=200 ; after: total=1300 idle_all=1000 busy=300
# delta total=300 delta busy=100 -> 33.3 %

MEMINFO = "MemTotal:        4000000 kB\nMemFree:  500000 kB\nMemAvailable: 1000000 kB\n"
# used = (4000000-1000000)/4000000 = 75.0 %


def test_parse_cpu_percent():
    assert parse_cpu_percent(STAT_BEFORE, STAT_AFTER) == 33.3


def test_parse_cpu_percent_no_delta_is_zero():
    assert parse_cpu_percent(STAT_BEFORE, STAT_BEFORE) == 0.0


def test_parse_mem_percent():
    assert parse_mem_percent(MEMINFO) == 75.0


def test_parse_mem_percent_zero_total_is_zero():
    assert parse_mem_percent("MemTotal: 0 kB\nMemAvailable: 0 kB\n") == 0.0


def test_read_temp_c():
    assert read_temp_c("48312\n") == 48.3


def test_fetch_piload_returns_none_off_linux(monkeypatch):
    # Simule /proc illisible : la lecture lève OSError -> None.
    from pi_aggregator.sources import piload

    def boom(_self):
        raise OSError("no /proc here")

    monkeypatch.setattr(piload.Path, "read_text", boom)
    assert asyncio.run(fetch_piload()) is None
```

- [ ] **Step 2 : Lancer → échec**

Run (depuis `pi-aggregator/`) :
```bash
python -m pytest tests/test_piload.py -q
```
Expected: FAIL (`ModuleNotFoundError` / `ImportError`, le module n'existe pas).

- [ ] **Step 3 : Écrire `sources/piload.py`**

```python
"""Charge du Raspberry Pi : CPU %, RAM %, température CPU.

Lecture locale de /proc et /sys (aucune dépendance ; le Pi est sous Linux).
Sur une plateforme sans /proc (macOS de dev, certains runners CI), fetch_piload
renvoie None et la clé "piload" est omise du JSON (widget « Not available »).
La température est omise si /sys/class/thermal n'est pas lisible.
"""

import asyncio
from pathlib import Path

CPU_SAMPLE_DELAY = 0.3


def _cpu_times(stat: str) -> tuple[int, int]:
    """(total, idle_all) à partir de la ligne agrégée « cpu » de /proc/stat."""
    for line in stat.splitlines():
        if line.startswith("cpu "):
            fields = [int(x) for x in line.split()[1:]]
            idle_all = fields[3] + fields[4]  # idle + iowait
            return sum(fields), idle_all
    return 0, 0


def parse_cpu_percent(stat_before: str, stat_after: str) -> float:
    total_b, idle_b = _cpu_times(stat_before)
    total_a, idle_a = _cpu_times(stat_after)
    d_total = total_a - total_b
    if d_total <= 0:
        return 0.0
    d_idle = idle_a - idle_b
    return round(100.0 * (d_total - d_idle) / d_total, 1)


def parse_mem_percent(meminfo: str) -> float:
    total = avail = 0
    for line in meminfo.splitlines():
        if line.startswith("MemTotal:"):
            total = int(line.split()[1])
        elif line.startswith("MemAvailable:"):
            avail = int(line.split()[1])
    if total <= 0:
        return 0.0
    return round(100.0 * (total - avail) / total, 1)


def read_temp_c(thermal_raw: str) -> float:
    return round(int(thermal_raw.strip()) / 1000.0, 1)


async def fetch_piload() -> dict | None:
    try:
        before = Path("/proc/stat").read_text()
        await asyncio.sleep(CPU_SAMPLE_DELAY)
        after = Path("/proc/stat").read_text()
        meminfo = Path("/proc/meminfo").read_text()
    except OSError:
        return None

    result: dict = {
        "cpu": parse_cpu_percent(before, after),
        "ram": parse_mem_percent(meminfo),
    }
    try:
        result["temp"] = read_temp_c(
            Path("/sys/class/thermal/thermal_zone0/temp").read_text()
        )
    except OSError:
        pass  # température indisponible -> champ omis
    return result
```

- [ ] **Step 4 : Lancer → vert**

Run (depuis `pi-aggregator/`) :
```bash
python -m pytest tests/test_piload.py -q
ruff check pi_aggregator/sources/piload.py tests/test_piload.py
```
Expected: PASS (6 tests), ruff propre.

- [ ] **Step 5 : Commit**

```bash
git add pi-aggregator/pi_aggregator/sources/piload.py pi-aggregator/tests/test_piload.py
git commit -m "feat(pi-aggregator): source de charge du Pi (CPU/RAM/température)"
```

---

### Task 2 : Config + câblage agrégateur

**Files:**
- Modify: `pi-aggregator/pi_aggregator/config.py`
- Modify: `pi-aggregator/pi_aggregator/aggregator.py`
- Modify: `pi-aggregator/config.example.toml`
- Test: `pi-aggregator/tests/test_piload.py` (ajout)

**Interfaces:**
- Consumes : `fetch_piload` (Task 1), `Source`/`Aggregator` (existants).
- Produces :
  - `PiLoadConfig(enabled: bool = True, refresh_minutes: int = 1)`
  - `Config.piload: PiLoadConfig | None`
  - une `Source("piload", …)` ajoutée à l'agrégateur quand `cfg.piload` est défini.

- [ ] **Step 1 : Écrire les tests config + agrégateur (échouent)**

Ajouter à `pi-aggregator/tests/test_piload.py` :
```python
from datetime import timedelta

import httpx

from pi_aggregator.aggregator import Aggregator
from pi_aggregator.config import Config, PiLoadConfig, load_config


def test_piload_config_default_enabled(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("[piload]\nenabled = true\n")
    cfg = load_config(cfg_file)
    assert cfg.piload == PiLoadConfig(enabled=True, refresh_minutes=1)


def test_piload_disabled_gives_none(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("[piload]\nenabled = false\n")
    assert load_config(cfg_file).piload is None


def test_piload_absent_gives_none(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("")  # pas de section [piload]
    assert load_config(cfg_file).piload is None


def test_aggregator_includes_piload_source_when_configured():
    cfg = Config(layout_file=Path("layout.json"), piload=PiLoadConfig())
    agg = Aggregator(cfg, client=httpx.AsyncClient())
    assert any(s.name == "piload" for s in agg.sources)


def test_aggregator_omits_piload_source_when_none():
    cfg = Config(layout_file=Path("layout.json"))
    agg = Aggregator(cfg, client=httpx.AsyncClient())
    assert not any(s.name == "piload" for s in agg.sources)
```
(Ajouter `from pathlib import Path` en tête si absent.)

- [ ] **Step 2 : Lancer → échec**

Run :
```bash
python -m pytest tests/test_piload.py -q
```
Expected: FAIL (`ImportError: cannot import name 'PiLoadConfig'`).

- [ ] **Step 3 : `config.py` — ajouter la dataclass, le champ, le chargement**

Après `ClaudeConfig` :
```python
@dataclass(frozen=True)
class PiLoadConfig:
    enabled: bool = True
    refresh_minutes: int = 1
```
Dans `Config`, après `claude` :
```python
    piload: PiLoadConfig | None = None
```
Dans `load_config`, après le bloc `claude` :
```python
    piload_raw = raw.get("piload")
    piload_enabled = bool(piload_raw and piload_raw.get("enabled", True))
```
Et dans le `return Config(...)`, après `claude=...` :
```python
        piload=PiLoadConfig(**piload_raw) if piload_enabled else None,
```

- [ ] **Step 4 : `aggregator.py` — importer et ajouter la source**

En tête, avec les autres imports de sources :
```python
from .sources.piload import fetch_piload
```
Dans `Aggregator.__init__`, après le bloc `if cfg.claude:` :
```python
        if cfg.piload:
            self.sources.append(
                Source(
                    "piload",
                    lambda: fetch_piload(),
                    timedelta(minutes=cfg.piload.refresh_minutes),
                )
            )
```
(`fetch_piload` ne prend ni cfg ni client : le `lambda` respecte la signature `Callable[[], Awaitable]`.)

- [ ] **Step 5 : `config.example.toml` — documenter la section**

Ajouter (près des autres sections) :
```toml
[piload]
# Charge du Raspberry Pi (CPU/RAM/température). Lecture locale, aucune clé requise.
enabled = true
# refresh_minutes = 1
```

- [ ] **Step 6 : Lancer → vert**

Run (depuis `pi-aggregator/`) :
```bash
python -m pytest tests/test_piload.py -q
ruff check .
```
Expected: PASS (11 tests au total dans ce fichier), ruff propre.

- [ ] **Step 7 : Commit**

```bash
git add pi-aggregator/pi_aggregator/config.py pi-aggregator/pi_aggregator/aggregator.py pi-aggregator/config.example.toml pi-aggregator/tests/test_piload.py
git commit -m "feat(pi-aggregator): câble la source piload (config + agrégateur)"
```

---

### Task 3 : Layout (Cal Events → PiLoad) + test de contrat

**Files:**
- Modify: `pi-aggregator/layout.json`
- Modify: `pi-aggregator/tests/test_contract.py`

**Interfaces:**
- Consumes : schéma de layout existant (clés underscore `Row_Height`/`Col_Width`).
- Produces : ID 2 `Active:false`, item ID 4096 « PiLoad » actif.

- [ ] **Step 1 : Écrire le test (échoue)**

Ajouter à `pi-aggregator/tests/test_contract.py` :
```python
def test_layout_remplace_cal_events_par_piload():
    layout = json.loads(LAYOUT_FILE.read_text())
    by_id = {i["ID"]: i for i in layout}
    # Cal Events (ID 2) désactivé
    assert by_id[2]["Active"] is False
    # PiLoad (ID 4096) actif, à la place de Cal Events
    piload = by_id.get(4096)
    assert piload is not None
    assert piload["Active"] is True
    assert piload["Description"] == "PiLoad"
    assert (piload["PosX"], piload["PosY"], piload["Width"], piload["Height"]) == (440, 255, 360, 145)
    assert set(piload) == set(GOLDEN["layout"][0])
```

- [ ] **Step 2 : Lancer → échec**

Run :
```bash
python -m pytest tests/test_contract.py::test_layout_remplace_cal_events_par_piload -q
```
Expected: FAIL (`KeyError: 4096` ou `by_id[2]["Active"]` est `True`).

- [ ] **Step 3 : Modifier `layout.json`**

(a) Sur l'entrée ID 2 « Cal Events », passer `"Active": true` → `"Active": false`.

(b) Ajouter cette entrée (mêmes clés/ordre que les autres) :
```json
  {
    "ID": 4096,
    "Description": "PiLoad",
    "Active": true,
    "PosX": 440,
    "PosY": 255,
    "Width": 360,
    "Height": 145,
    "Row_Height": 40,
    "Col_Width": 0,
    "Refresh": 1,
    "Group": 6,
    "Extra1": "",
    "Extra2": "",
    "Extra3": "",
    "Extra4": "",
    "Extra5": ""
  }
```

- [ ] **Step 4 : Lancer toute la suite → vert**

Run (depuis `pi-aggregator/`) :
```bash
python -m pytest -q
ruff check .
```
Expected: tous verts. Vérifier que `test_layout_par_defaut_respecte_le_contrat` (`len(layout) <= 15`, clés) et `test_layout_sans_widgets_supprimes` (interdit 4/32/512, pas 4096) passent toujours.

- [ ] **Step 5 : Commit**

```bash
git add pi-aggregator/layout.json pi-aggregator/tests/test_contract.py
git commit -m "feat(pi-aggregator): widget PiLoad (ID 4096) à la place de Cal Events"
```

---

### Task 4 : Firmware — `piload.cpp/.h` + parsing

**Files:**
- Create: `firmware/piload.h`
- Create: `firmware/piload.cpp`
- Modify: `firmware/fetchAllInfo.cpp` (appel de parse dans `fetchData()`, ≈ ligne 283)

**Interfaces:**
- Consumes : `LayoutItem` (`fetchAllInfo.h`), helpers de rendu (`drawSparseString`, `drawSparseChar`, `epaperFont`, `MDI_22_Sparse`, `GxEPD_BLACK` via `display.h`), `DynamicJsonDocument doc` dans `fetchData()`.
- Produces :
  - `struct PiLoadData { float cpu; float ram; float temp; bool hasTemp; bool valid; };` + `extern PiLoadData piload;`
  - `void parsePiLoad(JsonVariantConst obj);`
  - `void drawPiLoad(LayoutItem* item);`

- [ ] **Step 1 : Écrire `firmware/piload.h`**

```cpp
#pragma once
#include "fetchAllInfo.h"   // LayoutItem
#include <ArduinoJson.h>

struct PiLoadData {
  float cpu;     // % 0-100
  float ram;     // % 0-100
  float temp;    // °C (valide seulement si hasTemp)
  bool hasTemp;
  bool valid;    // true si la clé "piload" était présente
};

extern PiLoadData piload;

// Remplit `piload` depuis doc["piload"] (objet ou null).
void parsePiLoad(JsonVariantConst obj);

// Dessine le widget (CPU/RAM/temp, ou « Not available »).
void drawPiLoad(LayoutItem* item);
```

- [ ] **Step 2 : Écrire `firmware/piload.cpp`**

Rendu calqué sur `drawAmbient` (texte + icône MDI + repli indisponible inline,
le helper `drawUnavailableMessage` étant `static` dans fetchAllInfo.cpp).

```cpp
#include "piload.h"
#include "display.h"
#include <Arduino.h>

PiLoadData piload = {0.0f, 0.0f, 0.0f, false, false};

void parsePiLoad(JsonVariantConst obj) {
  piload.valid = obj.is<JsonObjectConst>();
  if (!piload.valid) {
    piload.hasTemp = false;
    return;
  }
  piload.cpu = obj["cpu"] | 0.0f;
  piload.ram = obj["ram"] | 0.0f;
  piload.hasTemp = obj["temp"].is<float>();
  piload.temp = obj["temp"] | 0.0f;
}

void drawPiLoad(LayoutItem* item) {
  if (!item) return;

  if (!piload.valid) {
    int cx = item->PosX + item->Width / 2;
    int cy = item->PosY + item->Height / 2;
    drawSparseStringCentered(&epaperFont, cx, cy - 8, "Not available", GxEPD_BLACK);
    drawSparseStringCentered(&epaperFont, cx, cy + 10, "at the moment", GxEPD_BLACK);
    return;
  }

  int x = item->PosX + 20;
  int y = item->PosY + 40;
  char buf[24];

  snprintf(buf, sizeof(buf), "CPU  %.0f %%", piload.cpu);
  drawSparseString(&epaperFont, x, y, buf, GxEPD_BLACK);

  y += 40;
  snprintf(buf, sizeof(buf), "RAM  %.0f %%", piload.ram);
  drawSparseString(&epaperFont, x, y, buf, GxEPD_BLACK);

  if (piload.hasTemp) {
    y += 40;
    drawSparseChar(&MDI_22_Sparse, x, y, 0xF050F, GxEPD_BLACK);  // thermomètre
    snprintf(buf, sizeof(buf), "%.0f\xC2\xB0""C", piload.temp);   // \xC2\xB0 = U+00B0
    drawSparseString(&epaperFont, x + 30, y, buf, GxEPD_BLACK);
  }
}
```

- [ ] **Step 3 : Appeler `parsePiLoad` dans `fetchData()`**

Dans `firmware/fetchAllInfo.cpp`, ajouter l'include en tête (avec les autres) :
```cpp
#include "piload.h"
```
Puis, dans `fetchData()`, juste avant le `return true;` final (≈ ligne 285, après le bloc `doc["makerworld"]`) :
```cpp
    parsePiLoad(doc["piload"]);
```

- [ ] **Step 4 : Compiler (gate)**

Run (depuis `firmware/`) :
```bash
arduino-cli compile --profile xiao_esp32c6 .
```
Expected: compile. Résoudre toute erreur d'include ou de type ArduinoJson (`JsonVariantConst`, `is<JsonObjectConst>()`).

- [ ] **Step 5 : Commit**

```bash
git add firmware/piload.h firmware/piload.cpp firmware/fetchAllInfo.cpp
git commit -m "feat(firmware): parsing et rendu du widget charge du Pi"
```

---

### Task 5 : Firmware — dispatch ID 4096 (`firmware.ino`)

**Files:**
- Modify: `firmware/firmware.ino`

**Interfaces:**
- Consumes : `drawPiLoad(LayoutItem*)`, `piload` (via `#include "piload.h"`), `getLayout(uint16_t)`, `updatePartial(item, fn)`.
- Produces : widget ID 4096 rendu (full + partiel + démo).

- [ ] **Step 1 : Inclure le module**

En tête de `firmware.ino`, près de `#include "ambient.h"` :
```cpp
#include "piload.h"
```

- [ ] **Step 2 : Récupérer l'item aux TROIS sites `getLayout`**

À chaque endroit où `infoAmbient = getLayout(2048);` apparaît (mode démo ≈1238,
chemin principal ≈1517, re-fetch après `fetchData()` ≈1583), ajouter en dessous :
```cpp
  LayoutItem* infoPiLoad = getLayout(4096);
```
(Au re-fetch, c'est une réassignation : `infoPiLoad = getLayout(4096);` sans le type, comme les autres `infoX` du bloc.)

- [ ] **Step 3 : Drapeau d'activation (et recalcul après re-fetch)**

Près de `bool ambientIf = …` (≈1543) :
```cpp
  bool piloadIf = infoPiLoad && infoPiLoad->Active;
```
Et dans le bloc de re-fetch, juste après la réassignation de `ambientIf` (le `ambientIf = …` ajouté en PR #10) :
```cpp
  piloadIf = infoPiLoad && infoPiLoad->Active;   // recalcul après re-fetch
```

- [ ] **Step 4 : Rendu plein écran**

Dans la branche full refresh, à côté de `if (ambientIf) drawAmbient(infoAmbient);` :
```cpp
      if (piloadIf) drawPiLoad(infoPiLoad);
```

- [ ] **Step 5 : Rendu partiel**

Dans la branche partial, à côté de `if (ambientIf) updatePartial(infoAmbient, drawAmbient);` :
```cpp
    if (piloadIf)
      updatePartial(infoPiLoad, drawPiLoad);
```

- [ ] **Step 6 : Mode démo**

Dans `drawDemoScreen` : ajouter `infoPiLoad` à `items[]`, `"PiLoad"` à `labels[]`,
et passer la borne de boucle de **10 à 11** (Ambient l'avait portée à 10). Vérifier
que les deux tableaux et la borne valent 11.

- [ ] **Step 7 : Compiler (gate, deux profils)**

Run (depuis `firmware/`) :
```bash
arduino-cli compile --profile xiao_esp32c6 .
FW=$(pwd); arduino-cli compile --profile esp32 --board-options PartitionScheme=custom --build-property "build.custom_partitions=$FW/partitions.csv" --build-property "upload.maximum_size=3604480" .
```
Expected: les deux compilent (XIAO ~42 %, esp32 ~38 %).

- [ ] **Step 8 : Commit**

```bash
git add firmware/firmware.ino
git commit -m "feat(firmware): branche le widget charge du Pi (ID 4096) au dispatch"
```

---

## Vérification finale (manuelle, hors plan automatisable)

- **CI** : jobs XIAO-ESP32C6 + esp32 verts ; `pytest`/`ruff` Pi verts.
- **Sur le vrai Pi** (propriétaire) : `curl http://localhost:8080/dashboard` montre
  `"piload": {"cpu":…, "ram":…, "temp":…}` ; le widget s'affiche à la place de
  Cal Events, avec la température.

## Notes de décomposition

- Tasks 1→3 (Pi) sont indépendantes des Tasks 4→5 (firmware) : seul le **contrat**
  les lie (clé `piload`, champs `cpu`/`ram`/`temp`). Les deux côtés respectent ce
  contrat ; ils peuvent être implémentés/relus en parallèle si besoin.
- Tasks 4→5 sont séquentielles (gate = compilation).
- Rappel transverse : `piloadIf` recalculé au re-fetch (Task 5 Step 3) — sinon le
  bug de la PR #10 réapparaît.
