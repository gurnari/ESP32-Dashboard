#pragma once
#include "configure.h"
#include "display.h"
#include <Arduino.h>
#include <cstring>

// Fixed buffers avoid Arduino String heap churn on long-running / deep-sleep cycles.
#define CFG_WIFI_SSID_MAX     33u   // 32 + NUL (802.11 SSID)
#define CFG_WIFI_PASS_MAX      65u   // WPA2-PSK max + NUL
#define CFG_PI_URL_MAX        131u   // Pi host[:port][/path] + NUL (matches URL builder)
#define CFG_MQTT_PASS_MAX      65u
#define CFG_MQTT_SN_MAX        65u
#define CFG_MQTT_IP_MAX        64u   // IPv4 literal or short hostname
#define CFG_ZIGBEE_STR_MAX     33u
#define CFG_CAL_TITLE_MAX     128u
#define CFG_PROXMOX_NAME_MAX   96u
#define CFG_TIMEZONE_MAX       65u

extern char wifi_ssid[CFG_WIFI_SSID_MAX];
extern char wifi_pass[CFG_WIFI_PASS_MAX];
extern char mqtt_pass[CFG_MQTT_PASS_MAX];
extern char mqtt_sn[CFG_MQTT_SN_MAX];
extern char mqtt_ip[CFG_MQTT_IP_MAX];
extern uint16_t mqtt_port;
extern char pi_url[CFG_PI_URL_MAX];
extern char device_timezone[CFG_TIMEZONE_MAX];

// Build the dashboard URL from the configured Raspberry Pi address.
// Accepts "192.168.1.50", "192.168.1.50:8080", "pi.local:8080" or a full
// "http://..." URL. Without an explicit path, "/dashboard" is appended.
// Plain HTTP by design: the Pi is on the local network and skipping TLS
// keeps the awake time (and battery drain) low.
inline const char* getApiUrl() {
    static char url[200];
    const char* host = pi_url;
    if (host[0] == '\0') return nullptr;
    if (std::strncmp(host, "http://", 7) == 0) host += 7;
    else if (std::strncmp(host, "https://", 8) == 0) host += 8;  // force HTTP
    if (host[0] == '\0') return nullptr;
    const bool hasPath = std::strchr(host, '/') != nullptr;
    snprintf(url, sizeof(url), "http://%s%s", host, hasPath ? "" : "/dashboard");
    return url;
}
