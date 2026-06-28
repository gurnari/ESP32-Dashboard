#include "ambient.h"
#include "configure.h"
#include "display.h"   // drawSparseString*, epaperFont, MDI_22_Sparse
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

void drawAmbient(LayoutItem* item) {
  if (!item) return;
  if (!ambient.valid) {
    int centerX = item->PosX + item->Width / 2;
    int centerY = item->PosY + item->Height / 2;
    drawSparseStringCentered(&epaperFont, centerX, centerY - 8,
                             "Not available", GxEPD_BLACK);
    drawSparseStringCentered(&epaperFont, centerX, centerY + 10,
                             "at the moment", GxEPD_BLACK);
    return;
  }

  int x = item->PosX + 24;
  int y = item->PosY + 60;
  char buf[16];

  // Température
  drawSparseChar(&MDI_22_Sparse, x, y, 0xF050F, GxEPD_BLACK);
  snprintf(buf, sizeof(buf), "%.0f\xC2\xB0""C", ambient.temperature);
  drawSparseStringCentered(&epaperFont, x + 130, y - 8, buf, GxEPD_BLACK);

  // Humidité
  y += 45;
  drawSparseChar(&MDI_22_Sparse, x, y, 0xF058E, GxEPD_BLACK);
  snprintf(buf, sizeof(buf), "%.0f %%", ambient.humidity);
  drawSparseStringCentered(&epaperFont, x + 130, y - 8, buf, GxEPD_BLACK);
}
