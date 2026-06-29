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
