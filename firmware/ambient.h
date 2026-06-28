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
