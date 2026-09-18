#include "progre_wifi.h"

#include <string.h>

#include "esp_check.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "nvs_flash.h"
#include "progre_settings.h"

#include "sdkconfig.h"

static const char *TAG = "PROGRE_WIFI";
static progre_wifi_state_t s_state = PROGRE_WIFI_OFFLINE;
static unsigned s_retry_count = 0;
static bool s_commissioning_scan = false;

#define PROGRE_WIFI_MAX_RETRIES 10

static void set_state(progre_wifi_state_t state)
{
    if (state != s_state) {
        s_state = state;
        ESP_LOGI(TAG, "State -> %s", progre_wifi_state_name(state));
    }
}

const char *progre_wifi_state_name(progre_wifi_state_t state)
{
    switch (state) {
        case PROGRE_WIFI_CONNECTING: return "CONNECTING";
        case PROGRE_WIFI_CONNECTED:  return "CONNECTED";
        default:                     return "OFFLINE";
    }
}

progre_wifi_state_t progre_wifi_get_state(void)
{
    return s_state;
}

static void wifi_event_handler(void *arg,
                               esp_event_base_t event_base,
                               int32_t event_id,
                               void *event_data)
{
    (void)arg;
    (void)event_data;

    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        s_retry_count = 0;
        set_state(PROGRE_WIFI_CONNECTING);
        esp_wifi_connect();
        return;
    }

    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        set_state(PROGRE_WIFI_OFFLINE);

        if (s_commissioning_scan) {
            ESP_LOGI(TAG, "Automatic reconnect paused for commissioning scan");
            return;
        }

        if (s_retry_count < PROGRE_WIFI_MAX_RETRIES) {
            ++s_retry_count;
            ESP_LOGW(TAG, "Disconnected; reconnect attempt %u/%u",
                     s_retry_count, PROGRE_WIFI_MAX_RETRIES);
            set_state(PROGRE_WIFI_CONNECTING);
            esp_wifi_connect();
        } else {
            ESP_LOGE(TAG, "Reconnect limit reached");
        }
        return;
    }

    if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        const ip_event_got_ip_t *event = event_data;
        s_retry_count = 0;
        set_state(PROGRE_WIFI_CONNECTED);
        ESP_LOGI(TAG, "IPv4 address: " IPSTR, IP2STR(&event->ip_info.ip));
    }
}

esp_err_t progre_wifi_init(void)
{
    esp_err_t err = nvs_flash_init();

    if (err == ESP_ERR_NVS_NO_FREE_PAGES ||
        err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }

    if (err != ESP_OK) {
        return err;
    }

    ESP_RETURN_ON_ERROR(esp_netif_init(), TAG, "esp_netif_init failed");
    ESP_RETURN_ON_ERROR(
        esp_event_loop_create_default(),
        TAG,
        "event loop creation failed"
    );

    esp_netif_create_default_wifi_sta();

    wifi_init_config_t init_cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_RETURN_ON_ERROR(
        esp_wifi_init(&init_cfg),
        TAG,
        "esp_wifi_init failed"
    );

    ESP_RETURN_ON_ERROR(
        esp_event_handler_register(
            WIFI_EVENT,
            ESP_EVENT_ANY_ID,
            &wifi_event_handler,
            NULL
        ),
        TAG,
        "Wi-Fi handler registration failed"
    );

    ESP_RETURN_ON_ERROR(
        esp_event_handler_register(
            IP_EVENT,
            IP_EVENT_STA_GOT_IP,
            &wifi_event_handler,
            NULL
        ),
        TAG,
        "IP handler registration failed"
    );

    ESP_RETURN_ON_ERROR(progre_settings_init(), TAG, "settings init failed");

    wifi_config_t wifi_cfg = {0};

    strlcpy((char *)wifi_cfg.sta.ssid, progre_settings_wifi_ssid(), sizeof(wifi_cfg.sta.ssid));
    strlcpy((char *)wifi_cfg.sta.password, progre_settings_wifi_password(), sizeof(wifi_cfg.sta.password));

    wifi_cfg.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;

    ESP_RETURN_ON_ERROR(
        esp_wifi_set_mode(WIFI_MODE_STA),
        TAG,
        "station mode failed"
    );

    ESP_RETURN_ON_ERROR(
        esp_wifi_set_config(WIFI_IF_STA, &wifi_cfg),
        TAG,
        "station config failed"
    );

    ESP_LOGI(TAG, "Wi-Fi station initialized for SSID '%s'", progre_settings_wifi_ssid());

    return esp_wifi_start();
}


esp_err_t progre_wifi_scan(progre_wifi_network_t *networks, size_t max_networks, size_t *count)
{
    if (!networks || !count || max_networks == 0) return ESP_ERR_INVALID_ARG;

    *count = 0;
    s_commissioning_scan = true;

    esp_err_t disconnect_err = esp_wifi_disconnect();
    if (disconnect_err != ESP_OK &&
        disconnect_err != ESP_ERR_WIFI_NOT_CONNECT) {
        s_commissioning_scan = false;
        return disconnect_err;
    }

    vTaskDelay(pdMS_TO_TICKS(250));

    wifi_scan_config_t cfg = {0};
    esp_err_t err = esp_wifi_scan_start(&cfg, true);

    if (err == ESP_OK) {
        uint16_t n = (uint16_t)(max_networks > 32 ? 32 : max_networks);
        wifi_ap_record_t records[32];

        err = esp_wifi_scan_get_ap_records(&n, records);

        if (err == ESP_OK) {
            for (uint16_t i = 0; i < n; ++i) {
                strlcpy(
                    networks[i].ssid,
                    (const char *)records[i].ssid,
                    sizeof(networks[i].ssid)
                );
                networks[i].rssi = records[i].rssi;
            }
            *count = n;
        }
    }

    s_commissioning_scan = false;

    s_retry_count = 0;
    set_state(PROGRE_WIFI_CONNECTING);

    esp_err_t reconnect_err = esp_wifi_connect();

    if (err != ESP_OK) return err;

    if (reconnect_err != ESP_OK &&
        reconnect_err != ESP_ERR_WIFI_CONN) {
        ESP_LOGW(TAG, "Post-scan reconnect returned: %s",
                 esp_err_to_name(reconnect_err));
    }

    return ESP_OK;
}

esp_err_t progre_wifi_apply_credentials(const char *ssid, const char *password)
{
    esp_err_t err = progre_settings_set_wifi(ssid, password);
    if (err != ESP_OK) return err;
    wifi_config_t cfg = {0};
    strlcpy((char *)cfg.sta.ssid, ssid, sizeof(cfg.sta.ssid));
    strlcpy((char *)cfg.sta.password, password, sizeof(cfg.sta.password));
    cfg.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    err = esp_wifi_set_config(WIFI_IF_STA, &cfg);
    if (err != ESP_OK) return err;
    esp_wifi_disconnect();
    return esp_wifi_connect();
}

esp_err_t progre_wifi_reconnect(void)
{
    esp_wifi_disconnect();
    return esp_wifi_connect();
}
