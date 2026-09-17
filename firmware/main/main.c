#include <stdio.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "esp_chip_info.h"
#include "esp_flash.h"
#include "esp_log.h"
#include "esp_timer.h"

static const char *TAG = "PROGRE";

void app_main(void)
{
    esp_chip_info_t chip_info;
    uint32_t flash_size = 0;

    esp_chip_info(&chip_info);
    esp_flash_get_size(NULL, &flash_size);

    ESP_LOGI(TAG, "================================");
    ESP_LOGI(TAG, "        PROGRE OS v0.1");
    ESP_LOGI(TAG, "          FIRST LIGHT");
    ESP_LOGI(TAG, "================================");

    ESP_LOGI(TAG,
             "ESP32-S3 cores=%d revision=%d",
             chip_info.cores,
             chip_info.revision);

    ESP_LOGI(TAG,
             "Flash: %lu MB",
             (unsigned long)(flash_size / (1024 * 1024)));

    ESP_LOGI(TAG, "Firmware skeleton is alive.");

    while (1) {
        ESP_LOGI(TAG,
                 "PROGRE heartbeat: %lld ms",
                 esp_timer_get_time() / 1000);

        vTaskDelay(pdMS_TO_TICKS(5000));
    }
}
