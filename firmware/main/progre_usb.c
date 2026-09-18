#include "progre_usb.h"

#include <stdio.h>
#include <string.h>
#include "cJSON.h"
#include "esp_app_desc.h"
#include "esp_log.h"
#include "esp_system.h"
#include "driver/usb_serial_jtag.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "progre_settings.h"
#include "progre_wifi.h"

static const char *TAG = "PROGRE_USB";

static void reply(cJSON *obj)
{
    char *text = cJSON_PrintUnformatted(obj);
    if (text) { printf("PROGRE_REPLY %s\n", text); fflush(stdout); cJSON_free(text); }
    cJSON_Delete(obj);
}

static cJSON *base_reply(const char *cmd, bool ok)
{
    cJSON *r = cJSON_CreateObject();
    cJSON_AddStringToObject(r, "cmd", cmd ? cmd : "unknown");
    cJSON_AddBoolToObject(r, "ok", ok);
    return r;
}

static void handle_line(char *line)
{
    const char prefix[] = "PROGRE ";
    if (strncmp(line, prefix, sizeof(prefix)-1) != 0) return;
    cJSON *q = cJSON_Parse(line + sizeof(prefix)-1);
    if (!q) { cJSON *r=base_reply("parse", false); cJSON_AddStringToObject(r,"error","invalid_json"); reply(r); return; }
    cJSON *cj = cJSON_GetObjectItemCaseSensitive(q, "cmd");
    const char *cmd = cJSON_IsString(cj) ? cj->valuestring : "";

    if (!strcmp(cmd, "status")) {
        cJSON *r=base_reply(cmd,true);
        cJSON_AddStringToObject(r,"device","progre");
        cJSON_AddStringToObject(r,"firmware","Progre OS");
        cJSON_AddStringToObject(r,"version",esp_app_get_description()->version);
        cJSON_AddStringToObject(r,"wifi_state",progre_wifi_state_name(progre_wifi_get_state()));
        cJSON_AddStringToObject(r,"ssid",progre_settings_wifi_ssid());
        cJSON_AddStringToObject(r,"bridge_host",progre_settings_bridge_host());
        cJSON_AddNumberToObject(r,"bridge_port",progre_settings_bridge_port());
        reply(r);
    } else if (!strcmp(cmd, "wifi_scan")) {
        progre_wifi_network_t nets[24]; size_t count=0;
        esp_err_t err=progre_wifi_scan(nets,24,&count);
        cJSON *r=base_reply(cmd,err==ESP_OK);
        cJSON *a=cJSON_AddArrayToObject(r,"networks");
        if (err==ESP_OK) for(size_t i=0;i<count;i++){ cJSON *n=cJSON_CreateObject(); cJSON_AddStringToObject(n,"ssid",nets[i].ssid); cJSON_AddNumberToObject(n,"rssi",nets[i].rssi); cJSON_AddItemToArray(a,n); }
        else cJSON_AddStringToObject(r,"error",esp_err_to_name(err));
        reply(r);
    } else if (!strcmp(cmd, "wifi_set")) {
        cJSON *ss = cJSON_GetObjectItemCaseSensitive(q, "ssid");
        cJSON *pw = cJSON_GetObjectItemCaseSensitive(q, "password");

        esp_err_t err =
            (cJSON_IsString(ss) && cJSON_IsString(pw))
            ? progre_settings_set_wifi(ss->valuestring, pw->valuestring)
            : ESP_ERR_INVALID_ARG;

        cJSON *r = base_reply(cmd, err == ESP_OK);

        if (err != ESP_OK) {
            cJSON_AddStringToObject(r, "error", esp_err_to_name(err));
        }

        /*
         * USB commissioning ACK comes first.
         * Do not make the host wait through a Wi-Fi state transition.
         */
        reply(r);

        if (err == ESP_OK) {
            vTaskDelay(pdMS_TO_TICKS(150));

            esp_err_t apply_err = progre_wifi_apply_credentials(
                progre_settings_wifi_ssid(),
                progre_settings_wifi_password()
            );

            if (apply_err != ESP_OK) {
                ESP_LOGE(
                    TAG,
                    "Applying commissioned Wi-Fi failed: %s",
                    esp_err_to_name(apply_err)
                );
            }
        }
    } else if (!strcmp(cmd, "bridge_set")) {
        cJSON *ho=cJSON_GetObjectItemCaseSensitive(q,"host"), *po=cJSON_GetObjectItemCaseSensitive(q,"port");
        esp_err_t err=(cJSON_IsString(ho)&&cJSON_IsNumber(po)) ? progre_settings_set_bridge(ho->valuestring,(uint16_t)po->valueint) : ESP_ERR_INVALID_ARG;
        cJSON *r=base_reply(cmd,err==ESP_OK); if(err!=ESP_OK)cJSON_AddStringToObject(r,"error",esp_err_to_name(err)); reply(r);
    } else if (!strcmp(cmd, "wifi_reconnect")) {
        esp_err_t err=progre_wifi_reconnect(); cJSON *r=base_reply(cmd,err==ESP_OK); if(err!=ESP_OK)cJSON_AddStringToObject(r,"error",esp_err_to_name(err)); reply(r);
    } else if (!strcmp(cmd, "reboot")) {
        cJSON *r=base_reply(cmd,true); reply(r); vTaskDelay(pdMS_TO_TICKS(150)); esp_restart();
    } else {
        cJSON *r=base_reply(cmd,false); cJSON_AddStringToObject(r,"error","unknown_command"); reply(r);
    }
    cJSON_Delete(q);
}

static void usb_task(void *arg)
{
    (void)arg;

    char line[512];
    size_t used = 0;

    usb_serial_jtag_driver_config_t cfg = {
        .tx_buffer_size = 1024,
        .rx_buffer_size = 1024,
    };

    esp_err_t err = usb_serial_jtag_driver_install(&cfg);

    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        ESP_LOGE(
            TAG,
            "USB Serial/JTAG driver init failed: %s",
            esp_err_to_name(err)
        );
        vTaskDelete(NULL);
        return;
    }

    setvbuf(stdout, NULL, _IONBF, 0);

    ESP_LOGI(TAG, "USB commissioning protocol ready");

    while (1) {
        uint8_t chunk[64];

        int n = usb_serial_jtag_read_bytes(
            chunk,
            sizeof(chunk),
            pdMS_TO_TICKS(50)
        );

        if (n <= 0) {
            continue;
        }

        for (int i = 0; i < n; ++i) {
            char c = (char)chunk[i];

            if (c == '\r') {
                continue;
            }

            if (c == '\n') {
                if (used > 0) {
                    line[used] = '\0';
                    handle_line(line);
                    used = 0;
                }
                continue;
            }

            if (used < sizeof(line) - 1) {
                line[used++] = c;
            } else {
                ESP_LOGW(TAG, "USB command exceeded input buffer");
                used = 0;
            }
        }
    }
}

esp_err_t progre_usb_control_init(void)
{
    BaseType_t ok=xTaskCreate(usb_task,"progre_usb",6144,NULL,5,NULL);
    return ok==pdPASS ? ESP_OK : ESP_ERR_NO_MEM;
}
