#include "progre_bridge.h"

#include <stdio.h>
#include <string.h>

#include "esp_http_client.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "progre_wifi.h"
#include "sdkconfig.h"

#include "progre_audio.h"
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


typedef struct {
    uint8_t *data;
    size_t capacity;
    size_t length;
    bool overflow;
} bridge_audio_response_t;


static esp_err_t bridge_audio_http_event(
    esp_http_client_event_t *evt)
{
    bridge_audio_response_t *response =
        evt->user_data;

    if (evt->event_id == HTTP_EVENT_ON_DATA &&
        response != NULL &&
        evt->data != NULL &&
        evt->data_len > 0) {

        size_t incoming =
            (size_t)evt->data_len;

        size_t available =
            response->capacity - response->length;

        if (incoming > available) {
            response->overflow = true;
            incoming = available;
        }

        if (incoming > 0) {
            memcpy(
                response->data + response->length,
                evt->data,
                incoming
            );

            response->length += incoming;
        }
    }

    return ESP_OK;
}


esp_err_t progre_bridge_exchange_audio(
    const int16_t *request_samples,
    size_t request_frames,
    int16_t *response_samples,
    size_t response_capacity_frames,
    size_t *response_frames)
{
    if (request_samples == NULL ||
        request_frames == 0 ||
        response_samples == NULL ||
        response_capacity_frames == 0 ||
        response_frames == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    *response_frames = 0;

    char url[160];

    snprintf(
        url,
        sizeof(url),
        "http://%s:%d/api/v1/audio",
        CONFIG_PROGRE_BRIDGE_HOST,
        CONFIG_PROGRE_BRIDGE_PORT
    );

    bridge_audio_response_t response = {
        .data = (uint8_t *)response_samples,
        .capacity =
            response_capacity_frames *
            sizeof(int16_t),
        .length = 0,
        .overflow = false,
    };

    esp_http_client_config_t config = {
        .url = url,
        .event_handler = bridge_audio_http_event,
        .user_data = &response,
        .timeout_ms = 10000,
        .buffer_size = 1024,
        .buffer_size_tx = 1024,
    };

    esp_http_client_handle_t client =
        esp_http_client_init(&config);

    if (client == NULL) {
        return ESP_ERR_NO_MEM;
    }

    esp_http_client_set_method(
        client,
        HTTP_METHOD_POST
    );

    esp_http_client_set_header(
        client,
        "Content-Type",
        "application/octet-stream"
    );

    esp_http_client_set_header(
        client,
        "X-Progre-Audio-Format",
        "pcm_s16le_mono_16000"
    );

    esp_http_client_set_post_field(
        client,
        (const char *)request_samples,
        request_frames * sizeof(int16_t)
    );

    ESP_LOGI(
        TAG,
        "AUDIO -> Bridge: %u frames / %u bytes",
        (unsigned)request_frames,
        (unsigned)(
            request_frames * sizeof(int16_t)
        )
    );

    esp_err_t result =
        esp_http_client_perform(client);

    if (result == ESP_OK) {

        int status =
            esp_http_client_get_status_code(client);

        ESP_LOGI(
            TAG,
            "Audio HTTP status: %d",
            status
        );

        if (status != 200) {
            result = ESP_FAIL;
        } else if (response.overflow) {
            ESP_LOGE(
                TAG,
                "Bridge audio response exceeded buffer"
            );

            result = ESP_ERR_NO_MEM;
        } else if (
            response.length == 0 ||
            (response.length % sizeof(int16_t)) != 0
        ) {
            ESP_LOGE(
                TAG,
                "Invalid Bridge audio response length: %u",
                (unsigned)response.length
            );

            result = ESP_ERR_INVALID_SIZE;
        } else {
            *response_frames =
                response.length /
                sizeof(int16_t);

            ESP_LOGI(
                TAG,
                "AUDIO <- Bridge: %u frames / %u bytes",
                (unsigned)*response_frames,
                (unsigned)response.length
            );
        }
    } else {
        ESP_LOGE(
            TAG,
            "Audio Bridge request failed: %s",
            esp_err_to_name(result)
        );
    }

    esp_http_client_cleanup(client);

    return result;
}


typedef struct {
    bool playback_started;
    bool playback_failed;
    size_t response_bytes;
    uint8_t carry_byte;
    bool have_carry;
} progre_audio_stream_response_t;


static esp_err_t progre_audio_stream_http_event(
    esp_http_client_event_t *evt
)
{
    progre_audio_stream_response_t *stream =
        (progre_audio_stream_response_t *)evt->user_data;

    if (stream == NULL) {
        return ESP_OK;
    }

    if (evt->event_id != HTTP_EVENT_ON_DATA ||
        evt->data == NULL ||
        evt->data_len <= 0) {
        return ESP_OK;
    }

    if (stream->playback_failed) {
        return ESP_FAIL;
    }

    if (!stream->playback_started) {
        esp_err_t err = progre_audio_stream_begin();

        if (err != ESP_OK) {
            stream->playback_failed = true;
            return err;
        }

        stream->playback_started = true;
    }

    const uint8_t *data =
        (const uint8_t *)evt->data;

    size_t len = (size_t)evt->data_len;
    size_t pos = 0;

    /*
     * HTTP chunks are byte-oriented and are not guaranteed to end
     * on a 16-bit PCM boundary. Preserve one odd byte between events.
     */
    if (stream->have_carry && len > 0) {
        uint8_t pair[2] = {
            stream->carry_byte,
            data[0]
        };

        int16_t sample =
            (int16_t)(
                ((uint16_t)pair[1] << 8) |
                (uint16_t)pair[0]
            );

        esp_err_t err =
            progre_audio_stream_write(&sample, 1);

        if (err != ESP_OK) {
            stream->playback_failed = true;
            return err;
        }

        stream->have_carry = false;
        pos = 1;
    }

    size_t usable = len - pos;

    if (usable & 1U) {
        stream->carry_byte =
            data[len - 1];

        stream->have_carry = true;
        usable--;
    }

    /*
     * Avoid alignment assumptions about HTTP's receive buffer.
     * Convert bounded chunks into aligned int16_t storage.
     */
    enum {
        HTTP_PCM_CHUNK_FRAMES = 256
    };

    int16_t samples[HTTP_PCM_CHUNK_FRAMES];

    size_t byte_pos = pos;
    size_t bytes_remaining = usable;

    while (bytes_remaining > 0) {
        size_t frames =
            bytes_remaining / sizeof(int16_t);

        if (frames > HTTP_PCM_CHUNK_FRAMES) {
            frames = HTTP_PCM_CHUNK_FRAMES;
        }

        for (size_t i = 0; i < frames; ++i) {
            uint8_t lo = data[byte_pos + i * 2];
            uint8_t hi = data[byte_pos + i * 2 + 1];

            samples[i] =
                (int16_t)(
                    ((uint16_t)hi << 8) |
                    (uint16_t)lo
                );
        }

        esp_err_t err =
            progre_audio_stream_write(
                samples,
                frames
            );

        if (err != ESP_OK) {
            stream->playback_failed = true;
            return err;
        }

        size_t consumed =
            frames * sizeof(int16_t);

        byte_pos += consumed;
        bytes_remaining -= consumed;
    }

    stream->response_bytes += len;

    return ESP_OK;
}


esp_err_t progre_bridge_exchange_audio_stream(
    const int16_t *request_samples,
    size_t request_frames
)
{
    if (request_samples == NULL ||
        request_frames == 0) {
        return ESP_ERR_INVALID_ARG;
    }

    if (progre_wifi_get_state() !=
        PROGRE_WIFI_CONNECTED) {
        ESP_LOGE(
            TAG,
            "AUDIO stream unavailable: Wi-Fi offline"
        );
        return ESP_ERR_INVALID_STATE;
    }

    char url[256];

    int url_len = snprintf(
        url,
        sizeof(url),
        "http://%s:%d/api/v1/audio",
        CONFIG_PROGRE_BRIDGE_HOST,
        CONFIG_PROGRE_BRIDGE_PORT
    );

    if (url_len <= 0 ||
        url_len >= (int)sizeof(url)) {
        return ESP_ERR_INVALID_SIZE;
    }

    progre_audio_stream_response_t stream = {
        0
    };

    esp_http_client_config_t config = {
        .url = url,
        .method = HTTP_METHOD_POST,
        .timeout_ms = 120000,
        .event_handler =
            progre_audio_stream_http_event,
        .user_data = &stream,
        .buffer_size = 2048,
    };

    esp_http_client_handle_t client =
        esp_http_client_init(&config);

    if (client == NULL) {
        return ESP_ERR_NO_MEM;
    }

    esp_err_t result = ESP_OK;

    size_t request_bytes =
        request_frames * sizeof(int16_t);

    ESP_LOGI(
        TAG,
        "AUDIO STREAM -> Bridge: %u frames / %u bytes",
        (unsigned)request_frames,
        (unsigned)request_bytes
    );

    esp_http_client_set_header(
        client,
        "Content-Type",
        "application/octet-stream"
    );

    esp_http_client_set_post_field(
        client,
        (const char *)request_samples,
        (int)request_bytes
    );

    esp_err_t perform_err =
        esp_http_client_perform(client);

    int status =
        esp_http_client_get_status_code(client);

    ESP_LOGI(
        TAG,
        "AUDIO STREAM HTTP status: %d",
        status
    );

    if (perform_err != ESP_OK) {
        ESP_LOGE(
            TAG,
            "AUDIO STREAM request failed: %s",
            esp_err_to_name(perform_err)
        );
        result = perform_err;
    } else if (status != 200) {
        ESP_LOGE(
            TAG,
            "AUDIO STREAM unexpected HTTP status: %d",
            status
        );
        result = ESP_FAIL;
    } else if (stream.playback_failed) {
        ESP_LOGE(
            TAG,
            "AUDIO STREAM playback failed"
        );
        result = ESP_FAIL;
    } else if (!stream.playback_started) {
        ESP_LOGE(
            TAG,
            "AUDIO STREAM response contained no PCM"
        );
        result = ESP_FAIL;
    } else if (stream.have_carry) {
        ESP_LOGE(
            TAG,
            "AUDIO STREAM response ended on odd PCM byte"
        );
        result = ESP_ERR_INVALID_SIZE;
    }

    /*
     * Always return the amplifier/codec to the quiet state if playback
     * was opened, even when HTTP later fails.
     */
    if (stream.playback_started) {
        esp_err_t end_err =
            progre_audio_stream_end();

        if (result == ESP_OK &&
            end_err != ESP_OK) {
            result = end_err;
        }
    }

    if (result == ESP_OK) {
        ESP_LOGI(
            TAG,
            "AUDIO STREAM <- Bridge: %u bytes complete",
            (unsigned)stream.response_bytes
        );
    }

    esp_http_client_cleanup(client);

    return result;
}
