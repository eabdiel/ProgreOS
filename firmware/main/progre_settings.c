#include "progre_settings.h"

#include <string.h>
#include "nvs.h"
#include "sdkconfig.h"

#define NS "progre"
static char s_ssid[33];
static char s_password[65];
static char s_bridge_host[96];
static uint16_t s_bridge_port;

static void load_string(nvs_handle_t h, const char *key, char *out, size_t cap, const char *fallback)
{
    size_t len = cap;
    if (nvs_get_str(h, key, out, &len) != ESP_OK) {
        strlcpy(out, fallback ? fallback : "", cap);
    }
}

esp_err_t progre_settings_init(void)
{
    nvs_handle_t h;
    esp_err_t err = nvs_open(NS, NVS_READONLY, &h);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        strlcpy(s_ssid, CONFIG_PROGRE_WIFI_SSID, sizeof(s_ssid));
        strlcpy(s_password, CONFIG_PROGRE_WIFI_PASSWORD, sizeof(s_password));
        strlcpy(s_bridge_host, CONFIG_PROGRE_BRIDGE_HOST, sizeof(s_bridge_host));
        s_bridge_port = CONFIG_PROGRE_BRIDGE_PORT;
        return ESP_OK;
    }
    if (err != ESP_OK) return err;
    load_string(h, "wifi_ssid", s_ssid, sizeof(s_ssid), CONFIG_PROGRE_WIFI_SSID);
    load_string(h, "wifi_pass", s_password, sizeof(s_password), CONFIG_PROGRE_WIFI_PASSWORD);
    load_string(h, "bridge_host", s_bridge_host, sizeof(s_bridge_host), CONFIG_PROGRE_BRIDGE_HOST);
    uint16_t port = CONFIG_PROGRE_BRIDGE_PORT;
    if (nvs_get_u16(h, "bridge_port", &port) != ESP_OK) port = CONFIG_PROGRE_BRIDGE_PORT;
    s_bridge_port = port;
    nvs_close(h);
    return ESP_OK;
}

const char *progre_settings_wifi_ssid(void) { return s_ssid; }
const char *progre_settings_wifi_password(void) { return s_password; }
const char *progre_settings_bridge_host(void) { return s_bridge_host; }
uint16_t progre_settings_bridge_port(void) { return s_bridge_port; }

esp_err_t progre_settings_set_wifi(const char *ssid, const char *password)
{
    if (!ssid || !ssid[0] || strlen(ssid) > 32 || !password || strlen(password) > 64) return ESP_ERR_INVALID_ARG;
    nvs_handle_t h;
    esp_err_t err = nvs_open(NS, NVS_READWRITE, &h);
    if (err != ESP_OK) return err;
    if ((err = nvs_set_str(h, "wifi_ssid", ssid)) == ESP_OK) err = nvs_set_str(h, "wifi_pass", password);
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h);
    if (err == ESP_OK) { strlcpy(s_ssid, ssid, sizeof(s_ssid)); strlcpy(s_password, password, sizeof(s_password)); }
    return err;
}

esp_err_t progre_settings_set_bridge(const char *host, uint16_t port)
{
    if (!host || !host[0] || strlen(host) >= sizeof(s_bridge_host) || port == 0) return ESP_ERR_INVALID_ARG;
    nvs_handle_t h;
    esp_err_t err = nvs_open(NS, NVS_READWRITE, &h);
    if (err != ESP_OK) return err;
    if ((err = nvs_set_str(h, "bridge_host", host)) == ESP_OK) err = nvs_set_u16(h, "bridge_port", port);
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h);
    if (err == ESP_OK) { strlcpy(s_bridge_host, host, sizeof(s_bridge_host)); s_bridge_port = port; }
    return err;
}
