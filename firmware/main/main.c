#include <stdbool.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_random.h"

#include "board_aipi_lite.h"
#include "progre_audio.h"
#include "progre_wifi.h"
#include "progre_bridge.h"
#include "progre_display.h"
#include "progre_usb.h"

static const char *TAG = "PROGRE";

#define BUTTON_DEBOUNCE_MS 30
#define MAIN_POLL_MS       10
#define BLINK_MIN_INTERVAL_MS 2800
#define BLINK_MAX_INTERVAL_MS 6500
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


enum {
    PROGRE_CAPTURE_MAX_SECONDS = 2,
    PROGRE_CAPTURE_MAX_FRAMES =
        PROGRE_AUDIO_SAMPLE_RATE *
        PROGRE_CAPTURE_MAX_SECONDS,};

static int16_t s_voice_capture[
    PROGRE_CAPTURE_MAX_FRAMES
];


void app_main(void)
{
    ESP_LOGI(TAG, "================================");
    ESP_LOGI(TAG, "        PROGRE OS v0.7");
    ESP_LOGI(TAG, "       PORTABLE COMPANION");
    ESP_LOGI(TAG, "================================");

    ESP_ERROR_CHECK(progre_display_init());
    talk_button_init();

    progre_display_show_companion(47, false, false, false);

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
    ESP_ERROR_CHECK(progre_usb_control_init());
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

    int companion_x = 47;
    int companion_dir = 1;
    bool walk_step = false;

    TickType_t next_walk =
        xTaskGetTickCount() +
        pdMS_TO_TICKS(350);

    bool stable_pressed = talk_button_raw_pressed();
    bool candidate_pressed = stable_pressed;

    TickType_t candidate_since = xTaskGetTickCount();
    size_t voice_capture_frames = 0;
    bool voice_capture_full = false;

    bool blink_active = false;
    TickType_t blink_until = 0;

    uint32_t blink_span =
        BLINK_MAX_INTERVAL_MS -
        BLINK_MIN_INTERVAL_MS + 1;

    TickType_t next_blink =
        xTaskGetTickCount() +
        pdMS_TO_TICKS(
            BLINK_MIN_INTERVAL_MS +
            (esp_random() % blink_span)
        );

    if (stable_pressed) {
        ESP_LOGI(TAG, "Talk button held at startup.");
        progre_display_show_companion(companion_x, true, false, walk_step);
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
                voice_capture_frames = 0;
                voice_capture_full = false;
                blink_active = false;
                progre_display_show_companion(companion_x, true, false, walk_step);
            } else {
                ESP_LOGI(
                    TAG,
                    "Talk button RELEASED — captured %u frames",
                    (unsigned)voice_capture_frames
                );


                if (microphone_ready &&
                    voice_capture_frames > 0) {

                    esp_err_t conversation_err =
                        progre_bridge_exchange_audio_stream(
                            s_voice_capture,
                            voice_capture_frames
                        );

                    if (conversation_err != ESP_OK) {
                        ESP_LOGW(
                            TAG,
                            "Conversation stream failed: %s",
                            esp_err_to_name(conversation_err)
                        );
                    }

                    progre_display_show_companion(47, false, false, false);
                }
            }
        }

        /*
         * Tiny companion roaming.
         * Walking pauses while listening or blinking.
         */
        if (!stable_pressed &&
            !blink_active &&
            now >= next_walk) {

            companion_x += companion_dir * 2;

            if (companion_x <= 4) {
                companion_x = 4;
                companion_dir = 1;
            } else if (
                companion_x >=
                PROGRE_LCD_WIDTH - 38
            ) {
                companion_x =
                    PROGRE_LCD_WIDTH - 38;
                companion_dir = -1;
            }

            walk_step = !walk_step;

            progre_display_show_companion(
                companion_x,
                false,
                false,
                walk_step
            );

            next_walk =
                now +
                pdMS_TO_TICKS(
                    260 + (esp_random() % 240)
                );
        }

        /*
         * Natural idle blink.
         *
         * Talking/listening always owns the display. Blink is only
         * allowed while idle and consists of one short second frame.
         */
        if (!stable_pressed) {
            if (blink_active) {
                if (now >= blink_until) {
                    blink_active = false;
                    progre_display_show_companion(47, false, false, false);

                    next_blink =
                        now +
                        pdMS_TO_TICKS(
                            BLINK_MIN_INTERVAL_MS +
                            (esp_random() % blink_span)
                        );
                }
            } else if (now >= next_blink) {
                blink_active = true;
                blink_until =
                    now +
                    pdMS_TO_TICKS(BLINK_DURATION_MS);

                progre_display_show_companion(companion_x, false, true, walk_step);
            }
        }

        /*
         * Capture microphone PCM while Talk is held.
         *
         * The public audio API extracts one slot from the duplicated
         * stereo microphone stream, producing 16 kHz signed-16 mono.
         */
        if (stable_pressed &&
            microphone_ready &&
            !voice_capture_full) {

            size_t remaining =
                PROGRE_CAPTURE_MAX_FRAMES -
                voice_capture_frames;

            if (remaining > 0) {

                size_t captured_now = 0;

                esp_err_t capture_result =
                    progre_audio_capture_mono(
                        &s_voice_capture[
                            voice_capture_frames
                        ],
                        remaining,
                        &captured_now,
                        50
                    );

                if (capture_result == ESP_OK) {
                    voice_capture_frames +=
                        captured_now;
                } else if (
                    capture_result != ESP_ERR_TIMEOUT
                ) {
                    ESP_LOGW(
                        TAG,
                        "Microphone capture unavailable: %s",
                        esp_err_to_name(capture_result)
                    );
                }
            }

            if (voice_capture_frames >=
                PROGRE_CAPTURE_MAX_FRAMES) {

                voice_capture_full = true;

                ESP_LOGI(
                    TAG,
                    "Voice capture reached %d-second commissioning limit",
                    PROGRE_CAPTURE_MAX_SECONDS
                );
            }
        }


    }
}
