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
