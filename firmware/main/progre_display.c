#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "board_aipi_lite.h"
#include "progre_display.h"

static const char *TAG = "PROGRE_DISPLAY";

static spi_device_handle_t lcd_spi;

#define CMD_SWRESET 0x01
#define CMD_SLPOUT  0x11
#define CMD_INVOFF  0x20
#define CMD_DISPON  0x29
#define CMD_CASET   0x2A
#define CMD_RASET   0x2B
#define CMD_RAMWR   0x2C
#define CMD_MADCTL  0x36
#define CMD_COLMOD  0x3A

#define COLOR_BLACK   0x0000
#define COLOR_DARK_GRAY 0x3186
#define COLOR_WHITE   0xFFFF

static esp_err_t lcd_tx(const void *data, size_t len)
{
    spi_transaction_t t = {
        .length = len * 8,
        .tx_buffer = data,
    };

    return spi_device_transmit(lcd_spi, &t);
}

static esp_err_t lcd_cmd(uint8_t cmd)
{
    gpio_set_level(PROGRE_LCD_PIN_DC, 0);
    return lcd_tx(&cmd, 1);
}

static esp_err_t lcd_data(const void *data, size_t len)
{
    gpio_set_level(PROGRE_LCD_PIN_DC, 1);
    return lcd_tx(data, len);
}

static void lcd_reset(void)
{
    gpio_set_level(PROGRE_LCD_PIN_RST, 0);
    vTaskDelay(pdMS_TO_TICKS(20));

    gpio_set_level(PROGRE_LCD_PIN_RST, 1);
    vTaskDelay(pdMS_TO_TICKS(120));
}

static void lcd_set_window(int x0, int y0, int x1, int y1)
{
    uint8_t data[4];

    lcd_cmd(CMD_CASET);

    data[0] = (x0 >> 8) & 0xFF;
    data[1] = x0 & 0xFF;
    data[2] = (x1 >> 8) & 0xFF;
    data[3] = x1 & 0xFF;
    lcd_data(data, sizeof(data));

    lcd_cmd(CMD_RASET);

    data[0] = (y0 >> 8) & 0xFF;
    data[1] = y0 & 0xFF;
    data[2] = (y1 >> 8) & 0xFF;
    data[3] = y1 & 0xFF;
    lcd_data(data, sizeof(data));

    lcd_cmd(CMD_RAMWR);
}

static void lcd_fill_rect(int x, int y, int w, int h, uint16_t color)
{
    if (x < 0 || y < 0 || w <= 0 || h <= 0) {
        return;
    }

    if (x + w > PROGRE_LCD_WIDTH) {
        w = PROGRE_LCD_WIDTH - x;
    }

    if (y + h > PROGRE_LCD_HEIGHT) {
        h = PROGRE_LCD_HEIGHT - y;
    }

    lcd_set_window(x, y, x + w - 1, y + h - 1);

    uint8_t row[PROGRE_LCD_WIDTH * 2];

    for (int i = 0; i < w; ++i) {
        row[i * 2]     = (color >> 8) & 0xFF;
        row[i * 2 + 1] = color & 0xFF;
    }

    gpio_set_level(PROGRE_LCD_PIN_DC, 1);

    for (int yy = 0; yy < h; ++yy) {
        lcd_tx(row, w * 2);
    }
}

static void lcd_clear(uint16_t color)
{
    lcd_fill_rect(
        0,
        0,
        PROGRE_LCD_WIDTH,
        PROGRE_LCD_HEIGHT,
        color
    );
}

/*
 * Tiny 5x7 glyph set containing only the letters needed for "PROGRE".
 * Bit 4 is the left-most pixel.
 */
typedef struct {
    char ch;
    uint8_t rows[7];
} glyph_t;

static const glyph_t glyphs[] = {
    {'P', {0x1E,0x11,0x11,0x1E,0x10,0x10,0x10}},
    {'R', {0x1E,0x11,0x11,0x1E,0x14,0x12,0x11}},
    {'O', {0x0E,0x11,0x11,0x11,0x11,0x11,0x0E}},
    {'G', {0x0E,0x11,0x10,0x17,0x11,0x11,0x0E}},
    {'E', {0x1F,0x10,0x10,0x1E,0x10,0x10,0x1F}},
};

static const uint8_t *glyph_for(char c)
{
    for (unsigned i = 0; i < sizeof(glyphs) / sizeof(glyphs[0]); ++i) {
        if (glyphs[i].ch == c) {
            return glyphs[i].rows;
        }
    }

    return NULL;
}

static void draw_char(int x, int y, char c, uint16_t color, int scale)
{
    const uint8_t *rows = glyph_for(c);

    if (!rows) {
        return;
    }

    for (int yy = 0; yy < 7; ++yy) {
        for (int xx = 0; xx < 5; ++xx) {
            if (rows[yy] & (1 << (4 - xx))) {
                lcd_fill_rect(
                    x + xx * scale,
                    y + yy * scale,
                    scale,
                    scale,
                    color
                );
            }
        }
    }
}

static void draw_word_progre(void)
{
    const char *text = "PROGRE";
    const int scale = 2;
    const int char_w = 5 * scale;
    const int spacing = 2;
    const int total_w = 6 * char_w + 5 * spacing;
    int x = (PROGRE_LCD_WIDTH - total_w) / 2;

    for (int i = 0; i < 6; ++i) {
        draw_char(x, 103, text[i], COLOR_WHITE, scale);
        x += char_w + spacing;
    }
}

static void draw_face(bool blink)
{
    /*
     * Simplified Progre face:
     * magenta frame, two eyes, central zig-zag mark.
     */

    lcd_fill_rect(25, 22, 78, 3, COLOR_DARK_GRAY);
    lcd_fill_rect(25, 22, 3, 60, COLOR_DARK_GRAY);
    lcd_fill_rect(100, 22, 3, 60, COLOR_DARK_GRAY);
    lcd_fill_rect(25, 79, 78, 3, COLOR_DARK_GRAY);

    if (blink) {
        lcd_fill_rect(39, 43, 15, 3, COLOR_WHITE);
        lcd_fill_rect(74, 43, 15, 3, COLOR_WHITE);
    } else {
        lcd_fill_rect(43, 40, 7, 9, COLOR_WHITE);
        lcd_fill_rect(78, 40, 7, 9, COLOR_WHITE);
    }

    /* center zig-zag */
    lcd_fill_rect(58, 55, 12, 3, COLOR_WHITE);
    lcd_fill_rect(67, 58, 3, 8, COLOR_WHITE);
    lcd_fill_rect(58, 63, 12, 3, COLOR_WHITE);
    lcd_fill_rect(58, 66, 3, 8, COLOR_WHITE);
    lcd_fill_rect(58, 71, 12, 3, COLOR_WHITE);
}

esp_err_t progre_display_init(void)
{
    ESP_LOGI(TAG, "Initializing AIPI Lite ST7735 display");

    gpio_config_t gpio_cfg = {
        .pin_bit_mask =
            (1ULL << PROGRE_LCD_PIN_DC) |
            (1ULL << PROGRE_LCD_PIN_RST) |
            (1ULL << PROGRE_LCD_PIN_BL),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };

    ESP_ERROR_CHECK(gpio_config(&gpio_cfg));

    gpio_set_level(PROGRE_LCD_PIN_BL, 0);
    gpio_set_level(PROGRE_LCD_PIN_DC, 0);
    gpio_set_level(PROGRE_LCD_PIN_RST, 1);

    spi_bus_config_t bus_cfg = {
        .mosi_io_num = PROGRE_LCD_PIN_MOSI,
        .miso_io_num = -1,
        .sclk_io_num = PROGRE_LCD_PIN_SCLK,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = PROGRE_LCD_WIDTH * 2 + 8,
    };

    ESP_ERROR_CHECK(
        spi_bus_initialize(SPI2_HOST, &bus_cfg, SPI_DMA_CH_AUTO)
    );

    spi_device_interface_config_t dev_cfg = {
        .clock_speed_hz = PROGRE_LCD_SPI_HZ,
        .mode = 0,
        .spics_io_num = PROGRE_LCD_PIN_CS,
        .queue_size = 1,
    };

    ESP_ERROR_CHECK(
        spi_bus_add_device(SPI2_HOST, &dev_cfg, &lcd_spi)
    );

    lcd_reset();

    ESP_ERROR_CHECK(lcd_cmd(CMD_SWRESET));
    vTaskDelay(pdMS_TO_TICKS(150));

    ESP_ERROR_CHECK(lcd_cmd(CMD_SLPOUT));
    vTaskDelay(pdMS_TO_TICKS(120));

    /*
     * 16-bit RGB565.
     */
    uint8_t colmod = 0x05;
    ESP_ERROR_CHECK(lcd_cmd(CMD_COLMOD));
    ESP_ERROR_CHECK(lcd_data(&colmod, 1));

    /*
     * Rotation 90 degrees.
     * MX + MV, RGB order.
     */
    uint8_t madctl = 0x60;
    ESP_ERROR_CHECK(lcd_cmd(CMD_MADCTL));
    ESP_ERROR_CHECK(lcd_data(&madctl, 1));

    ESP_ERROR_CHECK(lcd_cmd(CMD_INVOFF));

    ESP_ERROR_CHECK(lcd_cmd(CMD_DISPON));
    vTaskDelay(pdMS_TO_TICKS(20));

    lcd_clear(COLOR_BLACK);

    gpio_set_level(PROGRE_LCD_PIN_BL, 1);

    ESP_LOGI(TAG, "Display initialized");

    return ESP_OK;
}

void progre_display_draw_first_light(void)
{
    lcd_clear(COLOR_BLACK);
    draw_face(false);
    draw_word_progre();
}

void progre_display_set_blink(bool closed)
{
    /*
     * Redraw only the eye areas.
     */
    lcd_fill_rect(35, 36, 24, 18, COLOR_BLACK);
    lcd_fill_rect(69, 36, 24, 18, COLOR_BLACK);

    if (closed) {
        lcd_fill_rect(39, 43, 15, 3, COLOR_WHITE);
        lcd_fill_rect(74, 43, 15, 3, COLOR_WHITE);
    } else {
        lcd_fill_rect(43, 40, 7, 9, COLOR_WHITE);
        lcd_fill_rect(78, 40, 7, 9, COLOR_WHITE);
    }
}
