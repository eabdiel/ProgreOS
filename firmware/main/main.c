#include <stdbool.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "driver/gpio.h"
#include "esp_log.h"

#include "board_aipi_lite.h"
#include "progre_audio.h"
#include "progre_wifi.h"
#include "progre_bridge.h"
#include "progre_display.h"

static const char *TAG = "PROGRE";

#define BUTTON_DEBOUNCE_MS 30
#define MAIN_POLL_MS       10
#define BLINK_INTERVAL_MS  3000
#define BLINK_DURATION_MS  180
#define MIC_MEASURE_INTERVAL_MS 250

static void talk_button_init(void)
{
    gpio_config_t cfg = {
        .pin_bit_mask = (1ULL << PROGRE_BUTTON_TALK_PIN),
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };

    ESP_ERROR_CHECK(gpio_config(&cfg));
}

static bool talk_button_raw_pressed(void)
{
    return gpio_get_level(PROGRE_BUTTON_TALK_PIN) == 0;
}

void app_main(void)
{
    ESP_LOGI(TAG, "================================");
    ESP_LOGI(TAG, "        PROGRE OS v0.5");
    ESP_LOGI(TAG, "           CONNECTED");
    ESP_LOGI(TAG, "================================");

    ESP_ERROR_CHECK(progre_display_init());
    talk_button_init();

    progre_display_draw_first_light();

    ESP_LOGI(TAG, "Display active.");
    ESP_LOGI(TAG, "Talk button active on GPIO%d.", PROGRE_BUTTON_TALK_PIN);

    bool microphone_ready = false;

    esp_err_t audio_probe = progre_audio_probe_codec();
    if (audio_probe == ESP_OK) {
        ESP_LOGI(TAG, "Audio codec discovery PASS.");

        esp_err_t microphone_init = progre_audio_init_microphone();
        if (microphone_init == ESP_OK) {
            microphone_ready = true;
            ESP_LOGI(TAG, "Microphone initialization PASS.");

    esp_err_t wifi_err = progre_wifi_init();
    progre_bridge_init();
    if (wifi_err == ESP_OK) {
        ESP_LOGI(TAG, "Wi-Fi manager started.");
    } else {
        ESP_LOGE(TAG, "Wi-Fi initialization failed: %s",
                 esp_err_to_name(wifi_err));
    }

        } else {
            ESP_LOGW(TAG, "Microphone initialization unavailable: %s",
                     esp_err_to_name(microphone_init));
        }
    } else {
        ESP_LOGW(TAG, "Audio codec discovery unavailable: %s",
                 esp_err_to_name(audio_probe));
    }

    bool stable_pressed = talk_button_raw_pressed();
    bool candidate_pressed = stable_pressed;

    TickType_t candidate_since = xTaskGetTickCount();
    TickType_t last_blink = xTaskGetTickCount();
    TickType_t last_mic_measure = 0;

    if (stable_pressed) {
        ESP_LOGI(TAG, "Talk button held at startup.");
        progre_display_set_blink(true);
    }

    while (1) {
        TickType_t now = xTaskGetTickCount();
        bool raw_pressed = talk_button_raw_pressed();

        /*
         * Debounce GPIO42. A raw state must remain unchanged for
         * BUTTON_DEBOUNCE_MS before becoming the accepted state.
         */
        if (raw_pressed != candidate_pressed) {
            candidate_pressed = raw_pressed;
            candidate_since = now;
        }

        if (candidate_pressed != stable_pressed &&
            (now - candidate_since) >= pdMS_TO_TICKS(BUTTON_DEBOUNCE_MS)) {

            stable_pressed = candidate_pressed;

            if (stable_pressed) {
                ESP_LOGI(TAG, "Talk button PRESSED — listening");
                progre_display_set_blink(true);
            } else {
                ESP_LOGI(TAG, "Talk button RELEASED — idle");
                progre_display_set_blink(false);
                last_blink = now;
            }
        }

        /*
         * Hardware microphone validation.
         *
         * While the talk button is held, capture a short window
         * approximately four times per second and report signal
         * statistics for both I2S slots.
         */
        if (stable_pressed && microphone_ready &&
            (last_mic_measure == 0 ||
             (now - last_mic_measure) >=
                 pdMS_TO_TICKS(MIC_MEASURE_INTERVAL_MS))) {

            esp_err_t mic_result =
                progre_audio_measure_microphone();

            if (mic_result != ESP_OK) {
                ESP_LOGW(TAG,
                         "Microphone measurement unavailable: %s",
                         esp_err_to_name(mic_result));
            }

            last_mic_measure = xTaskGetTickCount();
        }

        /*
         * Autonomous blink only while idle.
         */
        if (!stable_pressed &&
            (now - last_blink) >= pdMS_TO_TICKS(BLINK_INTERVAL_MS)) {

            ESP_LOGI(TAG, "blink");
            progre_display_set_blink(true);

            vTaskDelay(pdMS_TO_TICKS(BLINK_DURATION_MS));

            progre_display_set_blink(false);
            last_blink = xTaskGetTickCount();
        }

        vTaskDelay(pdMS_TO_TICKS(MAIN_POLL_MS));
    }
}
