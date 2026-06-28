# Widget ambiant DHT11 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Afficher la température et l'humidité ambiantes via un DHT11 câblé localement sur l'ESP32 (XIAO ESP32C6), sans toucher au contrat JSON du Pi.

**Architecture:** Capteur local lu au réveil (comme l'horloge/batterie). Nouveau module firmware `ambient.cpp/.h` : pilote DHT11 bit-bang autonome + cache last-good en Preferences + rendu `drawAmbient`. Nouveau widget ID 2048 branché dans le dispatch de `firmware.ino`. Le Pi sert seulement l'entrée de layout (positions) dans `layout.json` ; aucune donnée ambiante ne transite par le JSON.

**Tech Stack:** C++/Arduino (esp32 core ≥3.0.0, GxEPD2), arduino-cli profils `sketch.yaml`. Côté Pi : JSON statique + pytest/ruff (inchangé fonctionnellement).

## Global Constraints

- Spec de référence : `docs/superpowers/specs/2026-06-28-dht11-ambient-widget-design.md`.
- **Aucune nouvelle dépendance de build** : pilote autonome, pas de lib Adafruit.
- **Aucune modification du contrat JSON** ni du code Python du Pi (hors `layout.json`).
- Broche DHT11 = **D6 (GPIO16)** sur le preset `XiaoEsp32C6` ; `PIN_UNASSIGNED` partout ailleurs.
- Widget **ID 2048** (512 interdit = ancien MakerWorld, cf `tests/test_contract.py`).
- Garde de compilation `#define USE_DHT11 1` dans `configure.h` ; garde runtime `hasDht11Pin()`.
- Gate de vérification firmware = **compilation** (pas de tests unitaires firmware).
  Le **profil XIAO est le gate liant** (carte cible) :
  - `arduino-cli compile --profile xiao_esp32c6 .` (depuis `firmware/`) — XIAO porte
    `huge_app` dans son fqbn, pas de flag custom.
  - Non-régression esp32 générique — ⚠️ le profil `sketch.yaml` esp32 n'inclut PAS le
    schéma de partition custom, donc `--profile esp32 .` SEUL déborde toujours
    (« text section exceeds available space ») : c'est attendu, pas une régression.
    Utiliser la commande CI complète :
    `FW=$(pwd); arduino-cli compile --profile esp32 --board-options PartitionScheme=custom --build-property "build.custom_partitions=$FW/partitions.csv" --build-property "upload.maximum_size=3604480" .`
    (≈38 % flash).
- Commits atomiques, convention conventionnelle. **Pas de mention Claude Code** dans les messages.
- Tout le code/affichage utilisateur est en français.

---

### Task 1 : Broche DHT11 + garde de compilation (`configure.h`)

**Files:**
- Modify: `firmware/configure.h` (struct `PinConfig`, `makePinPreset`, helpers, define)

**Interfaces:**
- Consumes: rien.
- Produces:
  - `struct PinConfig { …; int16_t dht11; }` (champ ajouté **en dernier**)
  - `bool hasDht11Pin()` → `true` si `activePins.dht11 >= 0`
  - macro `USE_DHT11` (valeur `1`)
  - preset `XiaoEsp32C6` : `dht11 = 16` ; tous les autres : `PIN_UNASSIGNED`

- [ ] **Step 1 : Ajouter le champ à la struct**

Dans `firmware/configure.h`, struct `PinConfig` (après `demoButton`) :

```cpp
  int16_t demoButton;
  int16_t dht11;       // DHT11 data pin (température/humidité ambiante locale)
};
```

- [ ] **Step 2 : Mettre à jour TOUS les presets de `makePinPreset`**

Chaque `return PinConfig{...}` a un champ de plus (dernier = dht11) :

```cpp
    case PinPreset::Esp32Waveshare:
      return PinConfig{15, 27, 26, 25, 13, 14, 33, 35, PIN_UNASSIGNED, PIN_UNASSIGNED};
    case PinPreset::Esp32C6Default:
      return PinConfig{1, 8, 14, 7, 23, 22, 4, 0, 2, PIN_UNASSIGNED};
    case PinPreset::Esp32C6SuperMini:
      return PinConfig{4, 20, 21, 22, 7, 5, 1, PIN_UNASSIGNED, 2, PIN_UNASSIGNED};
    case PinPreset::XiaoEsp32C6:
      // … commentaire existant + DHT11 sur D6(16).
      return PinConfig{1, 21, 22, 23, 19, 18, PIN_UNASSIGNED, 0, 2, 16};
    case PinPreset::Esp32Default:
      return PinConfig{15, 27, 26, 25, 13, 14, 4, 35, 33, PIN_UNASSIGNED};
    case PinPreset::Custom:
    default:
      return PinConfig{
        PIN_UNASSIGNED, PIN_UNASSIGNED, PIN_UNASSIGNED,
        PIN_UNASSIGNED, PIN_UNASSIGNED, PIN_UNASSIGNED,
        PIN_UNASSIGNED, PIN_UNASSIGNED, PIN_UNASSIGNED, PIN_UNASSIGNED
      };
```

Compléter le commentaire du preset XIAO : ajouter `DHT11 data=D6(16).`

- [ ] **Step 3 : Ajouter le helper + la garde de compilation**

À côté de `hasBatteryPin()` :

```cpp
inline bool hasDht11Pin() {
  return isPinAssigned(activePins.dht11);
}
```

En tête de `configure.h` (zone des `#define` de features) :

```cpp
#ifndef USE_DHT11
#define USE_DHT11 1   // 0 = pas de capteur DHT11 (aucun coût)
#endif
```

- [ ] **Step 4 : Vérifier que `setCustomPinConfig` / le portail gèrent le champ**

`setCustomPinConfig(const PinConfig&)` copie la struct entière → OK sans changement.
Vérifier `firmware.ino` autour de `saveCustomPinConfig` / chargement custom (≈ lignes 145, 1039, 1443) : si le code écrit/relit les champs **un par un** dans les Preferences, ajouter `dht11` à la même liste (sinon le preset Custom perdrait la broche). Si la struct est copiée en bloc, ne rien changer. Inspecter avant d'éditer ; n'ajouter le champ que si les autres y sont listés un par un.

- [ ] **Step 5 : Compiler (gate)**

Run (depuis `firmware/`) :
```bash
arduino-cli compile --profile xiao_esp32c6 .
arduino-cli compile --profile esp32 .
```
Expected: les deux compilent (XIAO ~42 %, esp32 ~38 %). Un échec d'initialiseur positionnel ici signale un `PinConfig{...}` oublié.

- [ ] **Step 6 : Commit**

```bash
git add firmware/configure.h firmware/firmware.ino
git commit -m "feat(firmware): broche DHT11 (D6) et garde USE_DHT11"
```

---

### Task 2 : Pilote DHT11 + cache (`ambient.cpp` / `ambient.h`)

**Files:**
- Create: `firmware/ambient.h`
- Create: `firmware/ambient.cpp`

**Interfaces:**
- Consumes (de Task 1) : `activePins.dht11`, `hasDht11Pin()`, `USE_DHT11`.
- Consumes (existant) : `extern Preferences prefs;` (déclaré dans `fetchAllInfo.cpp:23`, namespace `"ePaper"`), `LayoutItem` (`fetchAllInfo.h`).
- Produces :
  - `struct AmbientData { float temperature; float humidity; bool valid; };`
  - `extern AmbientData ambient;`
  - `bool readAmbient();` (remplit `ambient`, gère retry + cache, renvoie `true` si lecture capteur OK)
  - `void drawAmbient(LayoutItem* item);` (rendu — implémenté en Task 3)

- [ ] **Step 1 : Écrire le header `ambient.h`**

```cpp
#pragma once
#include "fetchAllInfo.h"   // LayoutItem

struct AmbientData {
  float temperature;  // °C (DHT11 : entier)
  float humidity;     // % HR (DHT11 : entier)
  bool valid;
};

extern AmbientData ambient;

// Lit le DHT11 (1 essai + 1 retry). En cas d'échec, recharge la dernière
// valeur connue depuis les Preferences. Renvoie true si la lecture capteur a
// réussi (false = valeur issue du cache ou indisponible).
bool readAmbient();

// Dessine le widget (température + humidité, ou « Not available »).
void drawAmbient(LayoutItem* item);
```

- [ ] **Step 2 : Écrire le pilote dans `ambient.cpp` (lecture + cache)**

```cpp
#include "ambient.h"
#include "configure.h"
#include <Arduino.h>
#include <Preferences.h>

extern Preferences prefs;   // namespace "ePaper", défini dans fetchAllInfo.cpp

AmbientData ambient = {0.0f, 0.0f, false};

// Attend que `pin` atteigne `level` ; renvoie la durée (µs) écoulée, ou -1 au
// timeout (`timeoutUs`).
static int32_t waitLevel(int pin, int level, uint32_t timeoutUs) {
  uint32_t start = micros();
  while (digitalRead(pin) != level) {
    if (micros() - start > timeoutUs) return -1;
  }
  return (int32_t)(micros() - start);
}

static void loadAmbientCache() {
  prefs.begin("ePaper", true);
  bool has = prefs.isKey("amb_t");
  float t = prefs.getFloat("amb_t", 0.0f);
  float h = prefs.getFloat("amb_h", 0.0f);
  prefs.end();
  if (has) {
    ambient.temperature = t;
    ambient.humidity = h;
    ambient.valid = true;
  }
}

static void saveAmbientCache() {
  prefs.begin("ePaper", false);
  prefs.putFloat("amb_t", ambient.temperature);
  prefs.putFloat("amb_h", ambient.humidity);
  prefs.end();
}

// Une tentative de lecture brute. Renvoie true + remplit out[5] si checksum OK.
static bool readRaw(int pin, uint8_t out[5]) {
  for (int i = 0; i < 5; i++) out[i] = 0;

  // Start signal : LOW ≥18 ms, puis relâche.
  pinMode(pin, OUTPUT);
  digitalWrite(pin, LOW);
  delay(20);
  pinMode(pin, INPUT_PULLUP);

  noInterrupts();
  // Réponse capteur : ~80µs LOW puis ~80µs HIGH.
  bool ok = waitLevel(pin, LOW, 90) >= 0
         && waitLevel(pin, HIGH, 90) >= 0
         && waitLevel(pin, LOW, 90) >= 0;
  if (ok) {
    for (int i = 0; i < 40 && ok; i++) {
      // Chaque bit : ~50µs LOW (start) puis HIGH dont la durée code 0/1.
      if (waitLevel(pin, HIGH, 70) < 0) { ok = false; break; }
      int32_t highDur = waitLevel(pin, LOW, 120);
      if (highDur < 0) { ok = false; break; }
      out[i / 8] <<= 1;
      if (highDur > 45) out[i / 8] |= 1;  // ~26-28µs=0, ~70µs=1
    }
  }
  interrupts();
  if (!ok) return false;

  uint8_t sum = out[0] + out[1] + out[2] + out[3];
  return sum == out[4];
}

bool readAmbient() {
#if USE_DHT11
  if (!hasDht11Pin()) {
    loadAmbientCache();
    return false;
  }
  int pin = activePins.dht11;
  uint8_t raw[5];
  bool ok = readRaw(pin, raw);
  if (!ok) {
    delay(1200);            // DHT11 : ≥1 s entre deux lectures
    ok = readRaw(pin, raw);
  }
  if (ok) {
    ambient.humidity = raw[0];      // partie entière (DHT11)
    ambient.temperature = raw[2];
    ambient.valid = true;
    saveAmbientCache();
    return true;
  }
  loadAmbientCache();               // échec → dernière valeur connue
  return false;
#else
  loadAmbientCache();
  return false;
#endif
}
```

- [ ] **Step 3 : Stub provisoire de `drawAmbient`**

Pour que `ambient.cpp` compile seul avant la Task 3, ajouter un rendu minimal (remplacé en Task 3) :

```cpp
#include "display.h"   // drawSparseString*, epaperFont

void drawAmbient(LayoutItem* item) {
  if (!item) return;
  // Implémentation finale en Task 3.
}
```

- [ ] **Step 4 : Compiler (gate)**

Run (depuis `firmware/`) :
```bash
arduino-cli compile --profile xiao_esp32c6 .
```
Expected: compile (le `.cpp`/`.h` sont pris automatiquement par le sketch). Résoudre toute erreur d'include (`fetchAllInfo.h`, `display.h`, `Preferences.h`).

- [ ] **Step 5 : Commit**

```bash
git add firmware/ambient.h firmware/ambient.cpp
git commit -m "feat(firmware): pilote DHT11 bit-bang avec cache last-good"
```

---

### Task 3 : Rendu du widget `drawAmbient` (`ambient.cpp`)

**Files:**
- Modify: `firmware/ambient.cpp` (remplacer le stub `drawAmbient`)

**Interfaces:**
- Consumes : `ambient` (Task 2), `LayoutItem`, helpers de rendu existants —
  `drawSparseString(const SparseGFXfont*, int16_t, int16_t, const char*, uint16_t)`,
  `drawSparseStringCentered(...)` (déclarés `display.h:13-14`),
  `epaperFont`, `MDI_22_Sparse` (via `display.h`),
  `drawSparseChar(const SparseGFXfont*, int16_t, int16_t, uint32_t, uint16_t)`.
- Produces : rendu visuel ; aucune nouvelle signature.

- [ ] **Step 1 : Remplacer le stub par le rendu final**

Modèle calqué sur `weatherWidget`/`makerWorldWidget` (icône MDI + texte). Icônes :
`0xF050F` = thermomètre, `0xF058E` = goutte/humidité (présentes dans `MDI_22_Sparse`).

```cpp
void drawAmbient(LayoutItem* item) {
  if (!item) return;
  if (!ambient.valid) {            // aucune valeur, même en cache
    drawUnavailableMessage(item);  // helper statique de fetchAllInfo.cpp
    return;
  }

  int x = item->PosX + 24;
  int y = item->PosY + 60;
  char buf[16];

  // Température
  drawSparseChar(&MDI_22_Sparse, x, y, 0xF050F, GxEPD_BLACK);
  snprintf(buf, sizeof(buf), "%.0f°C", ambient.temperature);
  drawSparseStringCentered(&epaperFont, x + 130, y - 8, buf, GxEPD_BLACK);

  // Humidité
  y += 45;
  drawSparseChar(&MDI_22_Sparse, x, y, 0xF058E, GxEPD_BLACK);
  snprintf(buf, sizeof(buf), "%.0f %%", ambient.humidity);
  drawSparseStringCentered(&epaperFont, x + 130, y - 8, buf, GxEPD_BLACK);
}
```

Note : `drawUnavailableMessage` est `static` dans `fetchAllInfo.cpp` (non exporté).
Deux options — choisir la plus propre dans le code existant :
1. recopier les deux lignes « Not available / at the moment » directement ici
   (centrées sur `item`, via `drawSparseStringCentered`) ; OU
2. retirer le `static` de `drawUnavailableMessage` et le déclarer dans `fetchAllInfo.h`.
Préférer l'option 1 (changement local, pas de modif d'API partagée).

- [ ] **Step 2 : Compiler (gate)**

Run (depuis `firmware/`) :
```bash
arduino-cli compile --profile xiao_esp32c6 .
```
Expected: compile. Vérifier que `MDI_22_Sparse`, `drawSparseChar`, `epaperFont` sont bien visibles via `display.h`.

- [ ] **Step 3 : Commit**

```bash
git add firmware/ambient.cpp
git commit -m "feat(firmware): rendu du widget ambiant (temp/humidité + icônes MDI)"
```

---

### Task 4 : Intégration dispatch (`firmware.ino`)

**Files:**
- Modify: `firmware/firmware.ino` (include, mode démo ≈1226-1255, chemin principal ≈1508-1740)

**Interfaces:**
- Consumes : `readAmbient()`, `drawAmbient(LayoutItem*)`, `ambient` (via `#include "ambient.h"`), `hasDht11Pin()`, `USE_DHT11`, `getLayout(uint16_t)`, `updatePartial(item, fn)`.
- Produces : widget ID 2048 rendu dans les deux chemins (full + partial).

- [ ] **Step 1 : Inclure le module**

En tête de `firmware.ino`, près des autres `#include "..."` :
```cpp
#include "ambient.h"
```

- [ ] **Step 2 : Lire le capteur au réveil**

Dans le flux principal (après le bloc `fetchData()`/refresh, avant le rendu,
≈ après ligne 1591), ajouter :
```cpp
#if USE_DHT11
  if (hasDht11Pin()) readAmbient();
#endif
```
(Lecture inconditionnelle d'`ambient` côté rendu : `readAmbient()` remplit aussi
depuis le cache si la lecture échoue.)

- [ ] **Step 3 : Récupérer l'item de layout (chemin principal)**

Après `LayoutItem* infoCalendar = getLayout(256);` (les deux occurrences,
≈1234 et ≈1516, ainsi que le re-fetch ≈1578) ajouter :
```cpp
  LayoutItem* infoAmbient = getLayout(2048);
```

- [ ] **Step 4 : Drapeau d'activation**

Près des autres `*If` (≈1543) :
```cpp
  bool ambientIf = infoAmbient && infoAmbient->Active;
```

- [ ] **Step 5 : Rendu plein écran**

Dans la branche full refresh (≈1692, à côté de `weatherWidget`) :
```cpp
      if (ambientIf) drawAmbient(infoAmbient);
```

- [ ] **Step 6 : Rendu partiel**

Dans la branche partial (≈1712, à côté de `updatePartial(infoOpenMeteo, weatherWidget)`) :
```cpp
    if (ambientIf)
      updatePartial(infoAmbient, drawAmbient);
```

- [ ] **Step 7 : Mode démo (optionnel mais cohérent)**

Dans `demoMode` (tableaux `items[]`/`labels[]` ≈1238-1244) : ajouter
`infoAmbient = getLayout(2048)` au-dessus, l'entrée dans `items[]`, `"Ambient"`
dans `labels[]`, et passer la borne de boucle de `9` à `10`. Vérifier les deux
tableaux ont la même taille.

- [ ] **Step 8 : Compiler (gate, deux profils)**

Run (depuis `firmware/`) :
```bash
arduino-cli compile --profile xiao_esp32c6 .
arduino-cli compile --profile esp32 .
```
Expected: les deux compilent. C'est le gate principal de toute la fonctionnalité.

- [ ] **Step 9 : Commit**

```bash
git add firmware/firmware.ino
git commit -m "feat(firmware): branche le widget ambiant DHT11 (ID 2048) au dispatch"
```

---

### Task 5 : Entrée de layout + test Pi (`layout.json`, `test_contract.py`)

**Files:**
- Modify: `pi-aggregator/layout.json` (ajout entrée ID 2048)
- Modify: `pi-aggregator/tests/test_contract.py` (test de présence)

**Interfaces:**
- Consumes : schéma de layout existant (clés `Row_Height`/`Col_Width` avec underscore).
- Produces : item de layout ID 2048 servi tel quel par `/dashboard`.

- [ ] **Step 1 : Écrire le test d'abord (échoue)**

Dans `pi-aggregator/tests/test_contract.py`, ajouter :
```python
def test_layout_contient_le_widget_ambiant():
    layout = json.loads(LAYOUT_FILE.read_text())
    item = next((i for i in layout if i["ID"] == 2048), None)
    assert item is not None, "widget ambiant (ID 2048) absent du layout"
    assert item["Active"] is True
    assert item["Description"] == "Ambient"
    # mêmes clés que le contrat (underscore sur Row_Height/Col_Width)
    assert set(item) == set(GOLDEN["layout"][0])
```

- [ ] **Step 2 : Lancer le test → échoue**

Run (depuis `pi-aggregator/`) :
```bash
python -m pytest tests/test_contract.py::test_layout_contient_le_widget_ambiant -q
```
Expected: FAIL (`item is None`).

- [ ] **Step 3 : Ajouter l'entrée dans `layout.json`**

Ajouter cet objet au tableau (mêmes clés/ordre que les autres ; valeurs `Extra*`
en chaînes vides) :
```json
  {
    "ID": 2048,
    "Description": "Ambient",
    "Active": true,
    "PosX": 10,
    "PosY": 155,
    "Width": 430,
    "Height": 130,
    "Row_Height": 45,
    "Col_Width": 0,
    "Refresh": 1,
    "Group": 1,
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
Expected: tous les tests passent (dont `test_layout_par_defaut_respecte_le_contrat`
qui vérifie `len(layout) <= 15` et les clés, et `test_layout_sans_widgets_supprimes`
qui interdit 512 — 2048 est autorisé). ruff propre.

- [ ] **Step 5 : Commit**

```bash
git add pi-aggregator/layout.json pi-aggregator/tests/test_contract.py
git commit -m "feat(pi-aggregator): entrée de layout pour le widget ambiant (ID 2048)"
```

---

## Vérification finale (manuelle, hors plan automatisable)

- **Compilation CI** : le job XIAO-ESP32C6 et le job esp32 de `.github/workflows/compile.yml` doivent passer (mêmes commandes que Task 4 Step 8).
- **Matériel** (par le propriétaire, pas d'accès ici) : DHT11 sur D6, flasher, vérifier l'affichage température/humidité, le retry (1ère lecture parfois ratée), et la persistance du cache (valeur affichée après un échec de lecture).

## Notes de décomposition

- Tasks 1→4 sont séquentielles (chaque gate = compilation). Task 5 (Pi) est indépendante des Tasks firmware et peut être faite en parallèle.
- ⚠️ Collision de slot : ID 2048 occupe la bande du widget Claude inactif (ID 1024). Réactiver Claude imposera de repositionner l'un des deux (documenté dans le spec).
