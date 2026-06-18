# Documentation de référence — Dashboard e-paper ESP32

> Document unique pour reprendre le projet à la main : architecture, fonctionnement
> détaillé des deux côtés (firmware + Pi), contrat JSON, build/flash, déploiement,
> dépannage et état d'avancement.
>
> Le projet est un **fork personnel** de `VoIPshare/ESP32-eInk-Dashboard`. Le but :
> supprimer la dépendance à Google Apps Script et déporter toute l'agrégation de
> données sur un Raspberry Pi du réseau local, en réutilisant tel quel le moteur de
> rendu du firmware. Voir aussi [`CLAUDE.md`](../CLAUDE.md) (cadrage projet) et les
> README de [`firmware/`](../firmware/README.md), [`pi-aggregator/`](../pi-aggregator/README.md)
> et [`pi-aggregator/golden/`](../pi-aggregator/golden/README.md).

---

## 1. Vue d'ensemble

Deux composants qui se parlent en **HTTP local** (pas de HTTPS, pas de cloud) :

```
   ┌─────────────────────────┐         HTTP GET /dashboard        ┌──────────────────────────┐
   │  ESP32 (XIAO ESP32C6)   │  ───────────────────────────────▶ │   Raspberry Pi (Python)  │
   │  + e-paper 7,5" + LiPo  │                                    │   FastAPI « agrégateur » │
   │                         │  ◀─────────────────────────────── │                          │
   │  réveil → 1 requête →   │        JSON consolidé unique       │  pré-agrège les sources  │
   │  rendu → deep sleep     │                                    │  (météo, colis, Claude…) │
   └─────────────────────────┘                                    └──────────────────────────┘
        sur batterie,                                               toujours allumé sur le LAN
   l'essentiel du temps endormi
```

**Deux principes directeurs** (issus de `CLAUDE.md`) :

1. **Un seul endpoint consolidé.** Le Pi pré-agrège tout dans un JSON unique. L'ESP32
   ne fait **qu'une requête HTTP par réveil** → temps éveillé minimal → autonomie maximale.
2. **Conserver le contrat JSON.** Le firmware sait déjà parser le JSON de l'ancien
   Apps Script. Le Pi produit **le même schéma** pour réutiliser le parsing/rendu
   existant (`fetchAllInfo.cpp`) sans le réécrire. Voir [§6](#6-le-contrat-json).

Ce qui **reste local à l'ESP32** : l'horloge (NTP) et la lecture batterie. Ce qui
**reste en MQTT direct** depuis l'ESP32 : le statut de l'imprimante Bambu Lab (hors
contrat HTTP). Tout le reste passe par le Pi.

---

## 2. Matériel

| Élément | Choix | Notes |
| ------- | ----- | ----- |
| MCU | Seeed **XIAO ESP32C6** | USB-C, gestion de charge LiPo intégrée, format minuscule. La radio Zigbee/Thread n'est pas utilisée. |
| Écran | Waveshare **e-Paper 7,5" monochrome** (« raw ») | 800×480, monochrome, piloté via GxEPD2. |
| Driver | Waveshare **e-Paper Driver HAT** | relie l'écran au XIAO en SPI. |
| Batterie | **LiPo 3,7 V / 1500 mAh** | sur les pads BAT du XIAO (négatif côté silk « D8 », positif côté « D5 »). En batterie, **aucune tension sur la broche 5V**. |

### Câblage XIAO ESP32C6 ↔ Driver HAT

Mapping défini dans le **preset `XiaoEsp32C6`** de [`firmware/configure.h`](../firmware/configure.h)
(`makePinPreset`). Colonne « Silk » = sérigraphie XIAO, « GPIO » = numéro réel utilisé dans le code.

| Fonction | Silk XIAO | GPIO | Champ `PinConfig` |
| -------- | --------- | ---- | ----------------- |
| EPD CS   | D1 | 1  | `epdCs` |
| EPD DC   | D3 | 21 | `epdDc` |
| EPD RST  | D4 | 22 | `epdRst` |
| EPD BUSY | D5 | 23 | `epdBusy` |
| SPI SCK  | D8 | 19 | `epdSck` |
| SPI MOSI | D10 | 18 | `epdMosi` |
| Alim panneau | — | — | `displayPower` = non assigné (HAT alimenté en 3V3) |
| Mesure batterie | A0 / D0 | 0 | `battery` |
| Bouton réveil/démo | D2 | 2 | `demoButton` (le réveil deep-sleep du C6 exige GPIO 0-7) |

> MISO (D9) n'est pas câblé : le panneau e-paper est en écriture seule.

### Autonomie et deep sleep

- Estimation `CLAUDE.md` : ~3 semaines à un refresh /15 min, ~6 semaines /30 min, **à condition
  que le deep sleep soit propre**.
- Cible deep sleep réaliste ~50 µA (le XIAO C6 vise 15 µA mais peut monter à 300-390 µA
  si mal configuré ou alimenté à 3,3 V — son PMIC LTH7R préfère ~3,7 V). **À mesurer au
  multimètre** une fois en place.
- Bien éteindre l'alim du panneau après affichage (`display.hibernate()` / `powerOff()`,
  cf. [§4.2](#42-cycle-de-vie--deep-sleep)).

### Lecture batterie

Pas de mesure « clé en main » sur le XIAO C6 : il faut **souder une résistance de 200 kΩ**
pour former un **pont diviseur 1:2** sur A0 (la tension lue est divisée par 2).

Côté code, [`readBattery()`](../firmware/firmware.ino) (≈ ligne 881) fait actuellement :
`analogReadResolution(12)`, une lecture `analogRead(A0)`, puis `raw * 3.3/4095 * 2.0 * 1.05`
(le `× 2.0` compense le pont, `1.05` = facteur de calibration à ajuster au multimètre).
Le pourcentage affiché est borné par `BAT_MIN_V = 3.0 V` et `BAT_MAX_V = 3.9 V`.

> **Point d'attention** : `CLAUDE.md` recommande `analogReadMilliVolts(A0)` moyenné sur
> ~16 mesures (plus stable que `analogRead` brut). Le code actuel ne moyenne pas et
> utilise `analogRead` — à améliorer si la lecture est bruitée sur le XIAO.

---

## 3. Flux de données (un réveil complet)

```
deep sleep ──(timer ~60 s OU bouton)──▶ setup()
  │
  ├─ charge la config NVS (Preferences) : wifi, pi_url, timezone, preset broches…
  ├─ wifi/pi_url manquants ? ─────────────▶ startAP()  (portail de config) → sleep
  ├─ bouton maintenu ? ───────────────────▶ AP (court) ou écran démo
  ├─ charge le layout en cache (Preferences)
  ├─ décide quels widgets sont « dus » ce réveil  (shouldFetchRefresh : bootCount % Refresh)
  │
  ├─ au moins un widget réseau dû ? ──▶ WiFi ON
  │        ├─ NTP (configTime UTC)
  │        ├─ besoin données consolidées ? ─▶ getApiUrl() → HTTP GET → fetchData() (parse JSON, met à jour le cache)
  │        ├─ Bambu dû ? ─▶ fetchBambu() (MQTT direct, hors Pi)
  │        └─ WiFi OFF
  │
  ├─ init SPI + display (full refresh tous les 60×24 réveils, sinon partial)
  ├─ dessine chaque widget actif et dû (clock chaque réveil ; autres selon Refresh)
  ├─ bootCount++
  └─ deep sleep aligné sur la minute suivante (+ wake bouton ext1)
```

Point clé pour l'autonomie : **la requête de l'ESP32 ne déclenche aucun appel réseau
côté Pi** — le Pi répond depuis son cache (rafraîchi en tâche de fond). L'ESP32 reste
donc éveillé le strict minimum.

---

## 4. Firmware (ESP32, C++/Arduino)

Dossier [`firmware/`](../firmware/). Fichiers clés :

| Fichier | Rôle |
| ------- | ---- |
| `firmware.ino` | sketch principal : `setup()`/`loop()`, deep sleep, portail de config, WiFi, batterie, horloge, orchestration du rendu. |
| `app.h` | buffers de config, déclarations globales, **`getApiUrl()`** (construction de l'URL du Pi). |
| `configure.h` | flags (`DEBUG`, `USE_ZIGBEE`…), constantes d'icônes MDI, **presets de broches** (`PinConfig`/`PinPreset`). |
| `fetchAllInfo.cpp/.h` | **parsing du JSON** (`fetchData()`), structures de données, cache Preferences du layout, plusieurs widgets (météo, tracking, stocks…). |
| `bambulab.cpp` | statut imprimante Bambu Lab en **MQTT direct** (TLS, hors Pi). |
| `proxmox.cpp` | widget « lecture d'un serveur » — **gabarit** pour de futurs widgets (ex. Claude). |
| `calendar.cpp` | widget calendrier mensuel. |
| `display.h` | configuration de l'écran GxEPD2 et helpers de dessin (`drawSparseString`…). |
| `partitions.csv` | table de partitions personnalisée (cible générique, voir [§4.9](#49-build--flash)). |
| `sketch.yaml` | profils de compilation `arduino-cli` (un par carte). |

### 4.1. Démarrage et portail de configuration

Au premier boot (ou après effacement NVS), `wifi_ssid`/`wifi_pass` sont vides → `setup()`
appelle **`startAP()`** : le XIAO crée un point d'accès WiFi **`Dashbboard-Setup`** (le double
« b » est dans le code) et sert une page sur **`http://192.168.4.1`** (`handleConfig` sur `/`,
`handleSave` en POST sur `/save`). L'écran affiche les instructions.

La page (`buildPage()`, ≈ ligne 286 de `firmware.ino`) stocke en NVS (`Preferences`, namespace
`config`) :

- SSID / mot de passe WiFi ;
- **adresse du Raspberry Pi** (champ « Raspberry Pi (IP[:port]) », clé `pi_url`) ;
- fuseau horaire de repli (`device_timezone`) ;
- IP / port / identifiants MQTT (pour Bambu) ;
- **preset de broches** (liste déroulante) + mapping personnalisé si `Custom` ;
- réglages Zigbee si le firmware Zigbee est compilé.

On peut rouvrir le portail à tout moment via le **bouton de réveil maintenu** (voir [§4.7](#47-bouton-démo--réveil)).

### 4.2. Cycle de vie & deep sleep

L'appareil n'utilise **pas** `loop()` (vide) : tout se passe dans `setup()`, qui se termine
par `esp_deep_sleep_start()`. À chaque réveil, le compteur RTC `bootCount` (persistant en
deep sleep via `RTC_DATA_ATTR`) s'incrémente.

- **Durée de sommeil** : alignée sur la minute suivante — `seconds_to_sleep = 61 - tm_sec`
  (60 s si NTP non synchronisé). L'appareil se réveille donc ~chaque minute.
- **Réveils** : timer (`esp_sleep_enable_timer_wakeup`) **et** bouton (`esp_sleep_enable_ext1_wakeup`
  sur `demoButton`, réveil sur niveau HAUT).
- **Économie d'énergie écran** : `display.hibernate()` si le **prochain** boot est un full
  refresh (vide la RAM du contrôleur), sinon `display.powerOff()` (préserve la RAM pour le
  partial refresh). Si une broche d'alim panneau existe, son état est gelé (`gpio_hold_en`).

> Conséquence importante pour l'autonomie : l'horloge est rafraîchie **à chaque réveil
> (~chaque minute)** par un partial refresh, sans WiFi. Les estimations d'autonomie de
> `CLAUDE.md` (refresh /15-30 min) supposent un réveil moins fréquent — si l'autonomie est
> insuffisante, c'est le premier levier à revoir (allonger `seconds_to_sleep`).

### 4.3. Cadence de rafraîchissement par widget

Chaque widget de layout a un champ **`Refresh`** (en nombre de réveils ≈ minutes). La
fonction **`shouldFetchRefresh(item)`** renvoie vrai si le widget est actif et
`bootCount % Refresh == 0` (ou si un refresh est forcé après le mode démo). C'est ce qui
décide, à chaque réveil, quels widgets sont « dus ».

- L'**horloge** (`clockIf`) est **toujours** mise à jour.
- Un **full refresh** complet de l'écran a lieu tous les `60 × 24` réveils (≈ 1×/jour) pour
  effacer le ghosting ; les autres réveils font du **partial refresh** ciblé par widget.

### 4.4. Connexion réseau et requête au Pi

Le WiFi n'est allumé **que si nécessaire** (`needWiFi` = au moins un widget réseau dû, ou
pas de données en cache, ou retry en attente). Une fois connecté :

1. `initTime()` → `configTime(0, 0, "pool.ntp.org", "time.nist.gov")` (heure en **UTC**, la
   timezone est appliquée à l'affichage par le widget horloge).
2. Si des données consolidées sont nécessaires, **`fetchData()`** est appelé.
3. Bambu (MQTT) est interrogé séparément si dû.
4. WiFi coupé (`WiFi.mode(WIFI_OFF)`).

**`getApiUrl()`** ([`app.h`](../firmware/app.h)) construit l'URL à partir de `pi_url` :

- accepte `192.168.1.50`, `192.168.1.50:8080`, `pi.local:8080` ou une URL `http://…` ;
- un préfixe `http://`/`https://` est retiré (le HTTPS est volontairement **forcé en HTTP**) ;
- **si aucun chemin n'est fourni, `/dashboard` est ajouté**.

Résultat type : `http://192.168.1.50:8080/dashboard`. La requête (`HTTPClient`, timeout 10 s)
est un simple `GET` ; pas de TLS (réseau local → moins de RAM et de temps éveillé).

> **Piège hérité à connaître** : `fetchData()` n'est réellement appelé que si
> `!hasStoredData || stocksIf || trackingIf || pendingApiRetry` (≈ ligne 1559 de
> `firmware.ino`). Autrement dit, le re-téléchargement du **JSON entier** (qui contient
> aussi `weather`, `layout`, `claude`…) est piloté par l'échéance de **tracking** (stocks
> étant supprimé côté Pi), le premier boot, ou un retry. Si tu ajoutes une source dont la
> fraîcheur doit déclencher le fetch indépendamment de tracking, il faut étendre cette
> condition.

### 4.5. Parsing JSON et cache

**`fetchData()`** ([`fetchAllInfo.cpp`](../firmware/fetchAllInfo.cpp)) :

1. remet les compteurs à zéro, vérifie le WiFi et l'URL ;
2. `GET` l'endpoint, refuse tout code HTTP ≠ 200 ;
3. désérialise dans un `DynamicJsonDocument` de **60 Ko** (capacité max du payload) ;
4. parse les clés de 1er niveau présentes : `layout`, `stocks`, `tracking`, `calEvents`,
   `weather`, `makerworld` (voir le [contrat §6](#6-le-contrat-json)) ;
5. **persiste le layout** en NVS (`saveLayout()`), pour pouvoir redessiner hors-ligne.

Le **layout est mis en cache** (`loadLayout()`/`saveLayout()`, namespace `ePaper`) : au
réveil, le firmware redessine depuis le cache même sans réseau. MakerWorld a son propre cache
(`saveMakerWorld`/`loadMakerWorld`), reliquat de l'upstream.

Une clé de 1er niveau **absente est tolérée** : le widget correspondant affiche
« Not available / at the moment » (`drawUnavailableMessage`).

### 4.6. Système de widgets

Chaque widget est identifié par un **ID = puissance de 2** ; `getLayout(id)` retrouve sa
`LayoutItem` (position, taille, `Refresh`, `Active`, champs `Extra1..5`). Le rendu est
**codé en dur** dans `setup()` (pas de boucle générique) : chaque widget dû est dessiné par
sa fonction.

| ID | Widget | Fonction de rendu | Source des données | Champs `Extra` utilisés |
| -- | ------ | ----------------- | ------------------ | ----------------------- |
| 1 | Horloge | `updateClock` | NTP local | `Extra1` = fuseau (ex. `CET-1CEST,M3.5.0,M10.5.0/3`) |
| 2 | Événements (jour) | `gCalWidget` | `calEvents` (Pi, **reporté**) | — |
| 4 | Bourse | `stockWidget` | `stocks` (**supprimé**) | — |
| 8 | Météo | `weatherWidget` | `weather` (Pi) | `Extra1`=lat, `Extra2`=lon, `Extra3`=jours |
| 16 | Suivi colis | `trackingWidget` | `tracking` (Pi) | — |
| 32 | Proxmox | `proxmoxWidget` | serveur direct (**supprimé**) | `Extra1`=hôte, `Extra2`=auth |
| 64 | Bambu Lab | `bambuWidget` / `makerWorldWidget` | MQTT direct | `Extra1`=modèle, `Extra3`=… |
| 128 | Batterie + version | `drawStatus` | A0 local | — |
| 256 | Calendrier (mois) | `drawCalendar` | `calEvents` (**reporté**) | — |
| 1024 | **Utilisation Claude** | *(à écrire)* | `claude` (Pi) | — réservé, `Active:false` |

- Le widget **batterie (128)** affiche aussi la version firmware (`FW_VERSION`) et des icônes
  d'état (impression en cours, retry API, Zigbee…), alignées à droite.
- L'**horloge (1)** applique le fuseau de `Extra1` (sinon `device_timezone`, sinon `UTC0`).
- Le widget **Claude (1024)** n'a **pas encore de rendu firmware** : l'ID est réservé dans
  `layout.json` (`Active:false`), à implémenter sur le gabarit de `proxmox.cpp` puis passer
  `Active:true`. La donnée est déjà produite par le Pi (voir [§5.4](#54-source-claude)).

**Full vs partial refresh** : en full, tous les widgets actifs sont redessinés dans une
passe `firstPage()/nextPage()`. En partial, chaque widget dû est mis à jour isolément via
`updatePartial(item, fonction)` (fenêtre partielle → moins de ghosting, refresh plus rapide).

### 4.7. Bouton démo / réveil

`readWakeButtonAction()` (≈ ligne 1272) lit l'état du bouton au réveil :

- maintien court → **mode démo** (`drawDemoScreen`, force un full refresh) ;
- maintien long (`BUTTON_LONG_HOLD_MS` = 6 s) → **rouvre le portail AP** pour reconfigurer ;
- (`BUTTON_HOLD_MS` = 2 s, `BUTTON_LONG_HOLD_MS` = 6 s).

### 4.8. Bambu Lab (MQTT direct, hors Pi)

Décision de migration : le statut imprimante **reste en MQTT direct depuis l'ESP32**
([`bambulab.cpp`](../firmware/bambulab.cpp), `WiFiClientSecure` + `setInsecure()`), il
**n'entre pas dans le contrat JSON HTTP**. Configuré via les champs MQTT du portail. C'est
le seul flux réseau du firmware qui n'est pas servi par le Pi.

### 4.9. Build & flash

Compilation via les **profils `arduino-cli`** de [`firmware/sketch.yaml`](../firmware/sketch.yaml).
Cœur ESP32 ≥ 3.x. Cible principale de ce fork : **`xiao_esp32c6`**.

```bash
cd firmware
arduino-cli compile --profile xiao_esp32c6 .          # carte cible (XIAO ESP32C6)
arduino-cli compile --profile esp32 \                 # carte d'origine (legacy)
  --board-options PartitionScheme=custom \
  --build-property "build.custom_partitions=$PWD/partitions.csv" \
  --build-property "upload.maximum_size=3604480" .
```

> **Piège partitions** (vérifié) :
> - Les boards **génériques** (`esp32:esp32:esp32`, FireBeetle, SuperMini) acceptent
>   `PartitionScheme=custom` + le `partitions.csv` du repo. Sans ces flags, la compilation
>   échoue (« text section exceeds available space ») car les profils n'embarquent pas le
>   schéma custom.
> - Le board **XIAO_ESP32C6 n'a PAS d'option `custom`**. On utilise donc `PartitionScheme=huge_app`
>   (3 Mo No-OTA), **intégré directement dans le fqbn du profil** `xiao_esp32c6`
>   (`esp32:esp32:XIAO_ESP32C6:PartitionScheme=huge_app`). Du coup `arduino-cli compile
>   --profile xiao_esp32c6 .` suffit, sans flags supplémentaires.

Tailles actuelles : XIAO ~42 % de flash (≈ 1,33 Mo / 3 Mo), esp32 ~38 %.

**Flash** : `arduino-cli upload --profile xiao_esp32c6 -p <port> .` (le XIAO se monte en USB-C).

**CI** : [`.github/workflows/compile.yml`](../.github/workflows/compile.yml) compile toutes
les cartes (matrice), dont `XIAO-ESP32C6`, et publie les binaires. Déclenchement manuel
(`workflow_dispatch`).

### 4.10. Ajouter / modifier un preset de broches

Pour une nouvelle carte, ajouter dans [`configure.h`](../firmware/configure.h) :
1. une valeur à l'enum `PinPreset` ;
2. un `case` dans `makePinPreset()` (le `PinConfig` complet) ;
3. un `case` dans la sélection `DEFAULT_PIN_PRESET` (macro `-DDEFAULT_PIN_PRESET_…`).

Puis dans [`firmware.ino`](../firmware/firmware.ino) : un `case` dans `pinPresetValue()`,
`pinPresetLabel()`, une ligne dans `parsePinPreset()` et dans la liste `pinPresetOptions`
(portail). Enfin un profil dans `sketch.yaml` et une entrée dans la matrice CI.

> Les trois `switch` sur `PinPreset` doivent rester exhaustifs (le compilateur peut le
> signaler). `A0` reste réservé à la mesure batterie.

### 4.11. Polices et accents français

Les polices (Montserrat converti pour GxEPD2) utilisent une **liste de glyphes figée**. Si
les caractères accentués (é è à ç ù ê î ô…) n'y sont pas, le texte français s'affiche
incomplet. Régénérer les polices via les outils de [`firmware/fonts/`](../firmware/fonts/)
en **conservant l'ordre des glyphes**. *(TODO — voir [§8](#8-état-davancement--reprise).)*

---

## 5. Agrégateur Raspberry Pi (Python)

Dossier [`pi-aggregator/`](../pi-aggregator/). Stack : **FastAPI + httpx (async) + uvicorn**.
Package `pi_aggregator`.

```
pi_aggregator/
  app.py             factory create_app(), lifespan, tâche de fond, routes
  aggregator.py      classe Source (cache last-good) + Aggregator (assemble le JSON)
  config.py          chargement config.toml (dataclasses frozen)
  sources/
    layout.py        lit layout.json (relu à chaque requête)
    weather.py       Open-Meteo
    tracking.py      PKGE (colis)
    claude_usage.py  Anthropic Usage Admin API (squelette)
layout.json          le layout servi au firmware (éditable sans reflasher l'ESP32)
config.example.toml  modèle de config (copier vers config.toml, gitignoré)
golden/dashboard.json référence du contrat JSON (voir §6)
tests/               pytest (forme produite vs golden, sans réseau)
```

### 5.1. Architecture & cache « last-good »

[`app.py`](../pi-aggregator/pi_aggregator/app.py) : `create_app()` est une **factory** ;
le `lifespan` ouvre un `httpx.AsyncClient` partagé et lance une **tâche de fond**
(`_refresh_loop`, tick **60 s**) qui rafraîchit les sources périmées.

[`aggregator.py`](../pi-aggregator/pi_aggregator/aggregator.py) :

- **`Source`** = (nom, fonction `fetch` async, période `refresh`). Garde `value` et
  `refreshed_at`. `stale` = jamais rafraîchie ou période dépassée. `refresh()` applique le
  **cache « dernière bonne valeur »** : une exception ou un `None` **conserve l'ancienne
  valeur** (le dashboard ne se vide jamais sur un échec réseau ; on retentera au tick suivant).
- **`Aggregator`** : construit la liste des sources **selon la config** (weather/tracking/claude
  seulement si configurées). `build()` assemble `{"layout": …}` + les sources ayant une valeur
  + `lastUpdated` (UTC `…Z`). `health()` expose la fraîcheur de chaque source.

Conséquence : **la requête `/dashboard` de l'ESP32 ne fait aucun appel réseau** — elle lit le
cache mémoire + relit `layout.json`. Réponse immédiate = réveil ESP32 minimal.

### 5.2. Source météo (`weather`)

[`weather.py`](../pi-aggregator/pi_aggregator/sources/weather.py) — **Open-Meteo**
(`/v1/forecast`, `timezone=auto`, `forecast_days` = 1-7). `shape_weather()` met les tableaux
`daily` à la forme du contrat : **sunrise/sunset tronqués à 16 caractères**
(`YYYY-MM-DDTHH:MM`, sans secondes — exigence firmware), `temp_max`/`temp_min`,
`weather_code` (code WMO entier ; l'icône est calculée côté firmware). 3 essais avec backoff.

### 5.3. Source suivi de colis (`tracking`)

[`tracking.py`](../pi-aggregator/pi_aggregator/sources/tracking.py) — **PKGE**
(`GET /v1/packages/list`, header `X-Api-Key`). `shape_tracking()` mappe chaque colis :
`tracking` (= `track_number`), `status` (= `last_status`), `deliveryStatus`
(= `delivery_status`), `lastChecked` (`yyyy-MM-dd HH:mm:ss`), `cached:true`. Limité à 5.

> Les littéraux `last_status`/`delivery_status` de PKGE sont **passés tels quels** : le
> firmware compare `status` à `"delivered"` et `deliveryStatus` à `"in_transit"` pour choisir
> l'icône. Ne pas les traduire/normaliser.

Sans `api_key` dans la config, la source est désactivée et la clé `tracking` est omise.

### 5.4. Source utilisation Claude (`claude`)

[`claude_usage.py`](../pi-aggregator/pi_aggregator/sources/claude_usage.py) — **Usage Admin
API d'Anthropic** (`GET /v1/organizations/usage_report/messages`, `bucket_width=1d`, fenêtre
de 7 jours, pagination `has_more`/`next_page`). Produit :

```json
{ "today": {"input_tokens": N, "output_tokens": N},
  "week":  {"input_tokens": N, "output_tokens": N} }
```

`week` = somme des 7 derniers jours glissants (UTC) ; `today` = seau du jour. Les
`input_tokens` incluent le cache (non-cachés + lus + écritures 5 min/1 h) pour refléter la
consommation réelle.

> ⚠️ **Caveat majeur** : l'Admin API exige une **clé Admin** (`sk-ant-admin…`), qui n'existe
> que pour une **organisation Console Anthropic** — **pas** sur un compte individuel
> (Pro/Max). Sans `admin_api_key`, la source est désactivée et la clé `claude` omise. Si la
> source doit changer (autre API, données locales Claude Code), **seule `fetch_claude_usage()`
> est à remplacer** — la forme JSON et le futur widget restent stables. Référence API :
> skill `claude-api`.

### 5.5. Source layout (`layout`)

[`layout.py`](../pi-aggregator/pi_aggregator/sources/layout.py) — lit `layout.json`
**à chaque requête** (modifications à chaud, sans reflasher l'ESP32). Tronqué à 15 items
(limite firmware). Erreur de lecture → `[]` (loggé). C'est ici qu'on déplace/active/désactive
les widgets : positions, tailles, `Refresh`, `Active`, champs `Extra`.

### 5.6. Configuration

[`config.py`](../pi-aggregator/pi_aggregator/config.py) lit `config.toml` (chemin explicite,
`$PI_AGGREGATOR_CONFIG`, ou racine du projet). **Fichier absent → config minimale** (layout
seul, pas de source réseau). Une source n'est activée que si sa clé est renseignée
(`tracking.api_key`, `claude.admin_api_key` non vides). Modèle complet :
[`config.example.toml`](../pi-aggregator/config.example.toml).

`config.toml` est **gitignoré** (il contient les clés API PKGE et Anthropic). Ne jamais le committer.

### 5.7. Endpoints

| Route | Réponse |
| ----- | ------- |
| `GET /dashboard` | JSON consolidé (le contrat — [§6](#6-le-contrat-json)). C'est ce que l'ESP32 appelle. |
| `GET /healthz` | `{"status":"ok","sources":{<nom>:<date ISO ou null>}}` — fraîcheur de chaque source. |

### 5.8. Installer, lancer, tester

```bash
cd pi-aggregator
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp config.example.toml config.toml          # puis renseigner coords + clés
uvicorn --factory pi_aggregator.app:create_app --host 0.0.0.0 --port 8080
curl http://localhost:8080/dashboard | python3 -m json.tool   # vérification
ruff check . && pytest                       # lint + tests (aucun appel réseau)
```

Les tests valident la **forme produite contre `golden/dashboard.json`** (clés
`Row_Height`/`Col_Width`, littéraux de statut, formats de date, limites, payload < 60 Ko).

### 5.9. Déploiement sur le Pi (à faire)

*Non encore réalisé* (voir [§8](#8-état-davancement--reprise)). Cible : un service **systemd**.
Exemple d'unité (`/etc/systemd/system/pi-aggregator.service`) :

```ini
[Unit]
Description=ESP32 dashboard aggregator
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=/home/pi/ESP32-Dashboard/pi-aggregator
ExecStart=/home/pi/ESP32-Dashboard/pi-aggregator/.venv/bin/uvicorn \
  --factory pi_aggregator.app:create_app --host 0.0.0.0 --port 8080
Restart=on-failure
User=pi

[Install]
WantedBy=multi-user.target
```

`sudo systemctl enable --now pi-aggregator`. Pense à fixer l'**IP du Pi** (DHCP réservé ou
statique) puisque l'ESP32 la stocke en dur via le portail.

---

## 6. Le contrat JSON

Le **firmware est la référence du contrat** (`fetchAllInfo.cpp::fetchData()`), pas l'ancien
script Google. Le Pi doit produire ce schéma à l'identique. Fixture de référence :
[`pi-aggregator/golden/dashboard.json`](../pi-aggregator/golden/dashboard.json) (+ son
[README](../pi-aggregator/golden/README.md)).

Clés de 1er niveau possibles : `layout`, `weather`, `tracking`, `claude`, `lastUpdated`
(+ héritées et non émises par le Pi : `stocks`, `calEvents`, `makerworld`). **Une clé absente
est tolérée** → widget « Not available ».

### Pièges à respecter absolument (vérifiés)

- **Layout** : clés **`Row_Height` / `Col_Width` avec underscore** (sinon lues à 0 par le
  firmware). `Extra1..5` sont des **chaînes**. Limite **15** items.
- **Tracking** : `status` comparé en dur à **`"delivered"`**, `deliveryStatus` à
  **`"in_transit"`**. Littéraux exacts. `lastChecked` au format `yyyy-MM-dd HH:mm:ss`.
  Limite **5**.
- **Weather** : `sunrise`/`sunset` en `char[16]` → **`YYYY-MM-DDTHH:MM` sans secondes**.
  `weather_code` = entier WMO (icône calculée côté firmware). Limite **7** jours.
- **calEvents** (si réintroduit) : `start`/`end` en **ISO 8601 UTC** (`…Z`) ; `parseISO8601()`
  ne lit que `%d-%d-%dT%d:%d:%d` et traite l'instant comme UTC. Events ≤ 10, `daysWithEvents` ≤ 31.
- **Claude** (ajout) : `{today,week} × {input_tokens,output_tokens}` (voir [§5.4](#54-source-claude)).
- **Payload total < 60 Ko** (capacité du `DynamicJsonDocument`).

### Exemple (forme produite par le Pi en Phase 1)

```json
{
  "layout": [ { "ID": 1, "Description": "Clock", "Active": true, "PosX": 10, "PosY": 0,
                "Width": 430, "Height": 155, "Row_Height": 10, "Col_Width": 10,
                "Refresh": 1, "Group": 1, "Extra1": "CET-1CEST,M3.5.0,M10.5.0/3",
                "Extra2": "", "Extra3": "", "Extra4": "", "Extra5": "" } ],
  "weather": [ { "sunrise": "2026-06-18T05:47", "sunset": "2026-06-18T21:58",
                 "temp_max": 24.1, "temp_min": 14.3, "weather_code": 3 } ],
  "tracking": [ { "tracking": "LX123", "status": "in_transit",
                  "deliveryStatus": "in_transit", "lastChecked": "2026-06-18 09:30:00",
                  "cached": true } ],
  "claude": { "today": {"input_tokens": 0, "output_tokens": 0},
              "week":  {"input_tokens": 0, "output_tokens": 0} },
  "lastUpdated": "2026-06-18T09:30:00.000Z"
}
```

---

## 7. Configuration de bout en bout — où mettre quoi

| Réglage | Emplacement | Effet |
| ------- | ----------- | ----- |
| WiFi, **adresse du Pi**, fuseau de repli, MQTT | **Portail ESP32** (`http://192.168.4.1`) → NVS | identité réseau de l'ESP32 ; bouton maintenu pour rouvrir le portail. |
| **Disposition des widgets** (position, taille, `Refresh`, `Active`, `Extra`) | **`pi-aggregator/layout.json`** | servi à chaque requête → modifiable **sans reflasher**. |
| **Coordonnées météo, clés API (PKGE, Anthropic), port** | **`pi-aggregator/config.toml`** (gitignoré) | active/désactive les sources et les paramètre. |
| **Broches, carte cible** | `firmware/configure.h` + `sketch.yaml` (compilation) ou portail (preset) | matériel ; nécessite reflash si changé en dur. |

> Les coordonnées météo existent à **deux endroits** : `config.toml` (`[weather]`, utilisé par
> le Pi pour appeler Open-Meteo) **et** `layout.json` ID 8 `Extra1/2/3` (hérité du firmware).
> Côté Pi-HTTP, c'est `config.toml` qui pilote l'appel réel ; les `Extra` du widget météo ne
> sont plus déterminants pour la donnée (le Pi a déjà formaté la prévision).

---

## 8. État d'avancement & reprise

| Phase | Contenu | État |
| ----- | ------- | ---- |
| Monorepo | firmware → `firmware/`, `pi-aggregator/` créé | ✅ fait (PR #2) |
| Golden | fixture du contrat JSON reconstituée | ✅ fait (PR #1) |
| Phase 1 | agrégateur Pi : FastAPI, sources weather/tracking/layout, cache last-good, tests | ✅ codé (PR #3) |
| Widget Claude | source `claude` côté Pi (squelette) | ✅ codé (PR #4) |
| Phase 2 | firmware → HTTP local Pi (fin de Google Apps Script) + preset XIAO ESP32C6 | ✅ codé (PR #5) |

### Reste à faire (TODO)

- **Déployer le Pi** en service systemd avec `config.toml` réel (clé PKGE, coords) et IP fixe — [§5.9](#59-déploiement-sur-le-pi-à-faire).
- **Renseigner la clé Anthropic** (si organisation Console disponible) ou rebrancher la source Claude sur une autre origine — [§5.4](#54-source-claude).
- **Écrire le widget firmware Claude** (ID 1024) sur le gabarit `proxmox.cpp`, puis `Active:true` dans `layout.json` — [§4.6](#46-système-de-widgets).
- **Régénérer les polices** avec les glyphes accentués français — [§4.11](#411-polices-et-accents-français).
- **Mesurer le deep sleep** au multimètre et, si besoin, allonger `seconds_to_sleep` pour l'autonomie — [§4.2](#42-cycle-de-vie--deep-sleep).
- **Décider du sort de `calEvents`** (CalDAV/ICS via le Pi ?) — actuellement reporté.

### Décidé / hors périmètre

- `stocks`, `makerworld`, `proxmox`, Google Calendar : **supprimés** du périmètre cible.
- Bambu Lab : **reste en MQTT direct** depuis l'ESP32 (hors contrat HTTP).
- Pas de HTTPS entre ESP32 et Pi ; pas de réintroduction de Google Apps Script.

---

## 9. Dépannage

| Symptôme | Pistes |
| -------- | ------ |
| Écran « Not available » sur un widget | clé absente du JSON (source non configurée côté Pi, ou échec persistant) ; vérifier `GET /healthz` et `config.toml`. |
| Tout l'écran figé / vieilles données | l'ESP32 redessine depuis le cache : WiFi KO, `pi_url` faux, ou Pi injoignable. Vérifier l'IP du Pi (DHCP ?) et `curl http://<pi>:8080/dashboard`. |
| Icône « retry API » sur la barre d'état | `fetchData()` a échoué ; `apiRetryStreak` s'incrémente, retry au prochain réveil. Vérifier le port/chemin (`/dashboard` ajouté seulement si pas de chemin). |
| Texte français tronqué (accents manquants) | polices à régénérer avec les glyphes accentués — [§4.11](#411-polices-et-accents-français). |
| Compilation « text section exceeds available space » | flags de partition manquants (boards génériques) ou mauvais `PartitionScheme` — [§4.9](#49-build--flash). |
| `clé claude` jamais présente | l'Admin API exige une organisation Console ; compte individuel non supporté — [§5.4](#54-source-claude). |
| Heure fausse | NTP non synchronisé au boot (le clock affiche alors l'heure de l'horloge interne) ; ou mauvais fuseau dans `layout.json` ID 1 `Extra1`. |
| Conso élevée en sommeil | deep sleep mal configuré / alim 3,3 V ; viser ~3,7 V, vérifier `hibernate()`/`powerOff()` — [§2](#2-matériel). |

---

## 10. Pour aller plus vite (cheat-sheet)

```bash
# Compiler + flasher le XIAO
cd firmware && arduino-cli compile --profile xiao_esp32c6 .
arduino-cli upload --profile xiao_esp32c6 -p /dev/tty.usbmodemXXXX .

# Lancer le Pi en local et vérifier le contrat
cd pi-aggregator && source .venv/bin/activate
uvicorn --factory pi_aggregator.app:create_app --host 0.0.0.0 --port 8080
curl -s http://localhost:8080/dashboard | python3 -m json.tool
curl -s http://localhost:8080/healthz   | python3 -m json.tool

# Qualité Pi
cd pi-aggregator && ruff check . && pytest

# Reconfigurer l'ESP32 : bouton maintenu ~6 s → AP « Dashbboard-Setup » → http://192.168.4.1
```
