idf_component_register(
    SRCS
        "main.c"
        "progre_display.c" "progre_audio.c"
    INCLUDE_DIRS
        "."
    REQUIRES
        esp_driver_gpio
        esp_driver_spi
        esp_driver_i2c
        esp_driver_i2s
)
