# Golden fixture — contrat JSON du dashboard

`dashboard.json` est la **référence du contrat JSON** consommé par le firmware ESP32
dans `fetchAllInfo.cpp::fetchData()`. L'agrégateur Raspberry Pi (`/pi-aggregator`)
doit produire ce schéma à l'identique pour réutiliser le parsing/rendu existant
sans modifier le firmware.

## Provenance

Reconstituée depuis l'ancien Apps Script (feuilles CSV + `script.js`), avant sa
suppression du repo — pas de capture réseau :

- `layout` ← feuille `Layout` (statique, reproductible tel quel)
- `stocks` ← feuille `Stocks` + mapping `getStockInfo()`
- `tracking` ← forme de `getTrackingInfo()` ; feuille `Tracking` vide
  (données live PKGE) → valeurs d'exemple
- `weather` ← forme de `fetchOpenMeteo()` (coords du Layout ID 8 : `44.501,-72.5674`, 4 jours) → exemple
- `calEvents` ← forme de `getCalendar()` → exemple
- `makerworld` ← forme de `getMakerWorldStats()` (designId du Layout ID 64) → exemple

`layout` est figé dans le repo ; les autres sections reproduisent la **forme exacte**
des appels live avec des valeurs plausibles.

## Pièges du contrat (à respecter côté Pi)

- Clés layout **`Row_Height` / `Col_Width`** (avec underscore) — sinon lues à 0.
- Statuts tracking littéraux **`"delivered"` / `"in_transit"`** (comparés en dur dans `trackingWidget`).
- Dates : `calEvents.start/end` en **ISO 8601 UTC** (`...Z`) ; `weather` sunrise/sunset
  **sans secondes** (`YYYY-MM-DDTHH:MM`) ; `tracking.lastChecked` en `yyyy-MM-dd HH:mm:ss`.
- Payload total **< 60 Ko** (capacité du `DynamicJsonDocument`).
- Limites firmware : layout 15, stocks 5, tracking 5, events 10, jours 31, weather 7.

## Cible vs origine

Cette fixture documente le contrat **d'origine** (Apps Script). Selon les décisions de
migration, le Pi n'émettra qu'un sous-ensemble : `stocks`, `makerworld` et `proxmox`
sont **supprimés** ; `calEvents` est **reporté** ; `weather`, `tracking`, `layout` sont conservés.
Le firmware tolère une clé de 1er niveau absente (le widget affiche « Not available »).

> Note : `getStockInfo()` mappe `prevClose` sur la colonne « Price Open » et `opening`
> sur « Price Close » — possible inversion d'origine, sans incidence car `stocks` est supprimé.
