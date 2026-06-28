# Widget ambiant DHT11 (température / humidité locales)

> Design validé le 2026-06-28. Branche : `feat/dht11-ambient`.

## Objectif

Afficher la **température et l'humidité ambiantes de la pièce où se trouve le
dashboard** via un capteur **DHT11 câblé sur l'ESP32** (Seeed XIAO ESP32C6).

C'est un capteur **local**, au même titre que l'horloge (ID 1) et la batterie
(ID 128) : il **ne passe pas par le contrat JSON du Pi**. L'ESP32 le lit pendant
son réveil, dessine le widget, puis se rendort. Le Pi ne produit **aucune**
donnée ambiante ; il sert uniquement l'**entrée de layout** (positions), comme il
le fait déjà pour les autres widgets locaux.

## Principe directeur respecté

- Aucune requête HTTP supplémentaire (le capteur est local, pas sur le Pi).
- Coût en temps éveillé minimal : une lecture, un retry conditionnel (~1,2 s) en
  cas d'échec de checksum, puis dodo. Voir [[json-contract]] (inchangé).

## Matériel & câblage

- Capteur : module **DHT11** (breakout 3 broches avec pull-up intégrée).
- Câblage XIAO ESP32C6 :
  - `VCC → 3V3`
  - `GND → GND`
  - `DATA → D6 (GPIO16)` — broche libre (D7/D9 le sont aussi ; A0=batterie,
    D2=bouton demo, D1/D3/D4/D5/D8/D10 = SPI écran).
- Alimentation : le DHT11 reste sur le 3V3 (courant de veille ~µA, acceptable en
  deep sleep). Couper le VCC via un GPIO est une optimisation reportée (YAGNI).

## Composants

### 1. Broche — `firmware/configure.h`

- Ajouter un champ `int16_t dht11;` à `struct PinConfig` (en dernière position
  pour ne pas casser les initialiseurs positionnels existants).
- Mettre à jour **tous** les presets de `makePinPreset()` :
  - `XiaoEsp32C6` → `16` (D6).
  - tous les autres presets et `Custom` → `PIN_UNASSIGNED`.
- Ajouter le helper `inline bool hasDht11Pin()` (sur le modèle de
  `hasBatteryPin()`). Il sert de **garde naturelle** : le widget ne s'active que
  si la broche est assignée.
- Garde de compilation : `#define USE_DHT11 1` dans `configure.h`. À `0`, aucun
  coût (pas de lecture, pas de rendu) pour les cartes sans capteur.

### 2. Pilote — `firmware/ambient.cpp` + `firmware/ambient.h` (nouveaux)

- Lecteur **bit-bang autonome** (pas de dépendance Adafruit ; sketch.yaml et le
  build Arduino IDE restent inchangés).
- Structure de données globale :
  ```cpp
  struct AmbientData { float temperature; float humidity; bool valid; };
  extern AmbientData ambient;
  ```
- Protocole DHT11 : start signal (LOW ≥18 ms), réponse, 40 bits, vérification du
  **checksum** (somme des 4 premiers octets == 5e octet).
- Stratégie de lecture (`bool readAmbient()`):
  1. une tentative ;
  2. si checksum invalide, **un retry** après ~1,2 s (le DHT11 rate souvent la
     première lecture, et impose ≥1 s entre deux lectures).
- **Cache last-good en Preferences** (mêmes Preferences que le reste du firmware) :
  - clés `amb_t` / `amb_h` ;
  - en cas d'échec total, charger la dernière valeur connue et l'afficher
    (cohérent avec le cache offline existant) ;
  - en cas de succès, mettre à jour le cache.

### 3. Rendu — `void drawAmbient(LayoutItem*)` dans `ambient.cpp`

- Affiche la température (« 21°C », gros) et l'humidité (« 48 % »), avec icônes
  MDI thermomètre (`0xF050F`) et goutte/humidité (`0xF058E`) — **déjà présentes**
  dans `MDI_22_Sparse` (inclus via `display.h`), dessinées avec `drawSparseChar`
  comme les icônes météo. Aucune régénération de police MDI nécessaire.
- Si `!ambient.valid` (aucune valeur, même en cache), afficher le message
  indisponible via `drawUnavailableMessage(item)` (helper existant dans
  `fetchAllInfo.cpp`).
- Réutilise `drawSparseString*` + `epaperFont`. Glyphes `°` (U+00B0) et `%`
  (U+0025) **confirmés présents** dans la CharMap (police FR régénérée, cf
  [[migration-decisions]] PR #7) → aucune régénération nécessaire.

### 4. Intégration dispatch — `firmware/firmware.ino`

- Nouvel **ID 2048** « Ambient ».
- Récupérer l'item : `LayoutItem* infoAmbient = getLayout(2048);`
- ⚠️ ID 512 = ancien MakerWorld, **interdit** par `tests/test_contract.py`
  (widget supprimé) → on prend 2048, le prochain bitmask libre.
- L'ajouter aux tableaux `items[]` / `labels[]` du flux de rendu principal
  (et au mode démo si pertinent).
- Appeler `readAmbient()` pendant le réveil (avant le rendu), sous garde
  `#if USE_DHT11` + `hasDht11Pin()`.
- Câbler `drawAmbient` dans la boucle de rendu et, le cas échéant, le refresh
  partiel (sur le modèle de `drawCalendar`).
- Header : déclarer `drawAmbient` / `readAmbient` / `ambient` dans `ambient.h`,
  inclus là où c'est nécessaire.

### 5. Layout — `pi-aggregator/layout.json`

- Ajouter une entrée **ID 2048** « Ambient » :
  - `Active: true`
  - `PosX: 10, PosY: 155, Width: 430, Height: 130` (slot Claude inactif).
  - `Refresh`, `Group` cohérents avec les autres widgets locaux.
  - Champs `Extra*` vides.
- ⚠️ **Collision connue** : ce slot est celui du widget Claude (ID 1024,
  `Active: false`). Réactiver Claude un jour nécessitera de repositionner l'un des
  deux. Documenté ici et dans le code.

## Ce qui ne change PAS

- Aucune modification du **contrat JSON** ni du `pi-aggregator` (hors l'entrée de
  layout). Pas de nouvelle source Python, pas de nouveau champ JSON.
- Aucune modification du flux Bambu/MQTT, météo, tracking.
- Pas de nouvelle dépendance de build (lecteur autonome).

## Tests & vérification

- **Compilation** : `arduino-cli compile --profile xiao_esp32c6 .` (depuis
  `firmware/`) doit passer ; vérifier la non-régression `--profile esp32`.
  Cf [[migration-decisions]] : XIAO utilise `huge_app` (pas de partition custom).
- **Pi** : `pytest` + `ruff` dans `pi-aggregator/` doivent rester verts (le
  layout.json est relu ; vérifier qu'aucun test golden ne casse sur la nouvelle
  entrée de layout).
- **Validation matérielle** (hors CI, sur le vrai montage) : brancher le DHT11
  sur D6, flasher, vérifier l'affichage temp/humidité et le retry/cache. À faire
  par le propriétaire (pas d'accès matériel ici).

## Décisions actées

- DHT11 **sur l'ESP32** (air au niveau du display), pas sur le Pi — choix
  utilisateur.
- Pilote **bit-bang autonome**, pas de lib Adafruit — choix utilisateur.
- Placement **slot Claude inactif** (ID 2048, 10/155/430/130) — choix utilisateur.
