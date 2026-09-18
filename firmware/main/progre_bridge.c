#include "progre_bridge.h"

#include <stdio.h>
#include <string.h>

#include "esp_http_client.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "progre_wifi.h"
#include "sdkconfig.h"

static const char *TAG = "PROGRE_BRIDGE";

#define RESPONSE_BUFFER_SIZE 512

typedef struct {
    char data[RESPONSE_BUFFER_SIZE];
    size_t length;
} bridge_response_t;


static esp_err_t bridge_http_event(esp_http_client_event_t *evt)
{
    bridge_response_t *response = evt->user_data;

    if (evt->event_id == HTTP_EVENT_ON_DATA &&
        response != NULL &&
        evt->data != NULL &&
        evt->data_len > 0) {

        size_t available =
            RESPONSE_BUFFER_SIZE - 1 - response->length;

        size_t copy_len =
            (size_t)evt->data_len < available
                ? (size_t)evt->data_len
                : available;

        if (copy_len > 0) {
            memcpy(
                response->data + response->length,
                evt->data,
                copy_len
            );

            response->length += copy_len;
            response->data[response->length] = '\0';
        }
    }

    return ESP_OK;
}


static void bridge_task(void *arg)
{
    (void)arg;

    ESP_LOGI(TAG, "Waiting for Wi-Fi...");

    while (progre_wifi_get_state() != PROGRE_WIFI_CONNECTED) {
        vTaskDelay(pdMS_TO_TICKS(250));
    }

    ESP_LOGI(TAG, "Wi-Fi ready.");

    char url[160];

    snprintf(
        url,
        sizeof(url),
        "http://%s:%d/api/v1/device/hello",
        CONFIG_PROGRE_BRIDGE_HOST,
        CONFIG_PROGRE_BRIDGE_PORT
    );

    const char *payload =
        "{"
        "\"device\":\"progre\","
        "\"firmware\":\"progre-os-v0.5-connected\","
        "\"capabilities\":["
            "\"display\","
            "\"button\","
            "\"microphone\","
            "\"speaker\","
            "\"wifi\""
        "]"
        "}";

    bridge_response_t response = {0};

    esp_http_client_config_t config = {
        .url = url,
        .event_handler = bridge_http_event,
        .user_data = &response,
        .timeout_ms = 5000,
    };

    esp_http_client_handle_t client =
        esp_http_client_init(&config);

    if (client == NULL) {
        ESP_LOGE(TAG, "HTTP client initialization failed.");
        vTaskDelete(NULL);
        return;
    }

    esp_http_client_set_method(
        client,
        HTTP_METHOD_POST
    );

    esp_http_client_set_header(
        client,
        "Content-Type",
        "application/json"
    );

    esp_http_client_set_post_field(
        client,
        payload,
        strlen(payload)
    );

    ESP_LOGI(
        TAG,
        "HELLO -> %s:%d",
        CONFIG_PROGRE_BRIDGE_HOST,
        CONFIG_PROGRE_BRIDGE_PORT
    );

    esp_err_t err =
        esp_http_client_perform(client);

    if (err == ESP_OK) {
        int status =
            esp_http_client_get_status_code(client);

        ESP_LOGI(
            TAG,
            "Bridge HTTP status: %d",
            status
        );

        if (status == 200 &&
            strstr(response.data, "WELCOME PROGRE") != NULL) {

            ESP_LOGI(
                TAG,
                "WELCOME <- Bridge"
            );

            ESP_LOGI(
                TAG,
                "Physical Bridge handshake PASS."
            );
        } else {
            ESP_LOGW(
                TAG,
                "Unexpected Bridge response: %s",
                response.data
            );
        }
    } else {
        ESP_LOGE(
            TAG,
            "Bridge request failed: %s",
            esp_err_to_name(err)
        );
    }

    esp_http_client_cleanup(client);

    vTaskDelete(NULL);
}


esp_err_t progre_bridge_init(void)
{
    BaseType_t result = xTaskCreate(
        bridge_task,
        "progre_bridge",
        6144,
        NULL,
        5,
        NULL
    );

    if (result != pdPASS) {
        ESP_LOGE(TAG, "Unable to create Bridge task.");
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI(TAG, "Bridge client started.");

    return ESP_OK;
}
