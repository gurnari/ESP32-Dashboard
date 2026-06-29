#include "piload.h"
#include "display.h"
#include <Arduino.h>
#include <Preferences.h>

extern Preferences prefs;

PiLoadData piload = {0.0f, 0.0f, 0.0f, false, false};

void savePiLoad() {
  prefs.begin("ePaper", false);
  prefs.putFloat("pl_cpu", piload.cpu);
  prefs.putFloat("pl_ram", piload.ram);
  prefs.putFloat("pl_temp", piload.temp);
  prefs.putBool("pl_has", piload.hasTemp);
  prefs.putBool("pl_valid", piload.valid);
  prefs.end();
}

void loadPiLoad() {
  prefs.begin("ePaper", true);
  piload.cpu     = prefs.getFloat("pl_cpu", 0.0f);
  piload.ram     = prefs.getFloat("pl_ram", 0.0f);
  piload.temp    = prefs.getFloat("pl_temp", 0.0f);
  piload.hasTemp = prefs.getBool("pl_has", false);
  piload.valid   = prefs.getBool("pl_valid", false);
  prefs.end();
}

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
  loadPiLoad();

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
