#pragma once

#include <stdint.h>
#include "esp_err.h"

esp_err_t progre_settings_init(void);
const char *progre_settings_wifi_ssid(void);
const char *progre_settings_wifi_password(void);
const char *progre_settings_bridge_host(void);
uint16_t progre_settings_bridge_port(void);
esp_err_t progre_settings_set_wifi(const char *ssid, const char *password);
esp_err_t progre_settings_set_bridge(const char *host, uint16_t port);
