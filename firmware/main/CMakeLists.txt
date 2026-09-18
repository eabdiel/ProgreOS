idf_component_register(
    SRCS
        "main.c"
        "progre_display.c" "progre_audio.c"
        "progre_wifi.c"
        "progre_bridge.c"
        "progre_settings.c"
        "progre_usb.c"
    INCLUDE_DIRS
        "."
    REQUIRES
        esp_app_format esp_http_client
        json
        esp_driver_gpio
        esp_driver_spi
        esp_driver_i2c
        esp_driver_i2s
        esp_driver_usb_serial_jtag
        nvs_flash
        esp_netif
        esp_event
        esp_wifi
)
