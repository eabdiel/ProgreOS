idf_component_register(
    SRCS
        "main.c"
        "progre_display.c" "progre_audio.c"
        "progre_wifi.c"
    INCLUDE_DIRS
        "."
    REQUIRES
        esp_driver_gpio
        esp_driver_spi
        esp_driver_i2c
        esp_driver_i2s
        nvs_flash
        esp_netif
        esp_event
        esp_wifi
)
