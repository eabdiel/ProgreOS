#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "esp_log.h"

#include "progre_display.h"

static const char *TAG = "PROGRE";

void app_main(void)
{
    ESP_LOGI(TAG, "================================");
    ESP_LOGI(TAG, "        PROGRE OS v0.1");
    ESP_LOGI(TAG, "          FIRST LIGHT");
    ESP_LOGI(TAG, "================================");

    ESP_ERROR_CHECK(progre_display_init());

    progre_display_draw_first_light();

    ESP_LOGI(TAG, "First Light display active.");

    while (1) {
        vTaskDelay(pdMS_TO_TICKS(3000));

        ESP_LOGI(TAG, "blink");
        progre_display_set_blink(true);

        vTaskDelay(pdMS_TO_TICKS(180));

        progre_display_set_blink(false);
    }
}
