#pragma once

#include "esp_err.h"

typedef enum {
    PROGRE_WIFI_OFFLINE = 0,
    PROGRE_WIFI_CONNECTING,
    PROGRE_WIFI_CONNECTED
} progre_wifi_state_t;

esp_err_t progre_wifi_init(void);
progre_wifi_state_t progre_wifi_get_state(void);
const char *progre_wifi_state_name(progre_wifi_state_t state);

#include <stddef.h>
#define PROGRE_WIFI_SSID_MAX 32

typedef struct {
    char ssid[PROGRE_WIFI_SSID_MAX + 1];
    int rssi;
} progre_wifi_network_t;

esp_err_t progre_wifi_scan(progre_wifi_network_t *networks, size_t max_networks, size_t *count);
esp_err_t progre_wifi_apply_credentials(const char *ssid, const char *password);
esp_err_t progre_wifi_reconnect(void);
