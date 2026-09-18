#include <stdbool.h>
#include <stdlib.h>
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


static void draw_pixel(int x, int y, uint16_t color)
{
    lcd_fill_rect(x, y, 1, 1, color);
}

static void draw_line(
    int x0,
    int y0,
    int x1,
    int y1,
    uint16_t color
)
{
    int dx = abs(x1 - x0);
    int sx = x0 < x1 ? 1 : -1;
    int dy = -abs(y1 - y0);
    int sy = y0 < y1 ? 1 : -1;
    int err = dx + dy;

    while (true) {
        draw_pixel(x0, y0, color);

        if (x0 == x1 && y0 == y1) {
            break;
        }

        int e2 = 2 * err;

        if (e2 >= dy) {
            err += dy;
            x0 += sx;
        }

        if (e2 <= dx) {
            err += dx;
            y0 += sy;
        }
    }
}

static void draw_circle(
    int cx,
    int cy,
    int radius,
    uint16_t color
)
{
    int x = radius;
    int y = 0;
    int err = 0;

    while (x >= y) {
        draw_pixel(cx + x, cy + y, color);
        draw_pixel(cx + y, cy + x, color);
        draw_pixel(cx - y, cy + x, color);
        draw_pixel(cx - x, cy + y, color);
        draw_pixel(cx - x, cy - y, color);
        draw_pixel(cx - y, cy - x, color);
        draw_pixel(cx + y, cy - x, color);
        draw_pixel(cx + x, cy - y, color);

        y++;

        if (err <= 0) {
            err += 2 * y + 1;
        }

        if (err > 0) {
            x--;
            err -= 2 * x + 1;
        }
    }
}


#define BANNER_HEIGHT 18
#define TINY_SCALE     2
#define TINY_W         34
#define TINY_H         32

static void tiny_px(int ox, int oy, int x, int y)
{
    lcd_fill_rect(
        ox + x * TINY_SCALE,
        oy + y * TINY_SCALE,
        TINY_SCALE,
        TINY_SCALE,
        COLOR_WHITE
    );
}

static void tiny_hline(
    int ox, int oy, int x0, int x1, int y)
{
    for (int x = x0; x <= x1; ++x) {
        tiny_px(ox, oy, x, y);
    }
}

static void draw_tiny_progre(
    int ox,
    int oy,
    bool active,
    bool blink,
    bool step)
{
    /*
     * 17 x 16 logical-pixel Tamagotchi-style Progre.
     * Rendered at 2x scale = 34 x 32 physical pixels.
     */

    tiny_hline(ox, oy, 5, 11, 0);
    tiny_px(ox, oy, 4, 1);
    tiny_px(ox, oy, 12, 1);

    tiny_px(ox, oy, 3, 2);
    tiny_px(ox, oy, 13, 2);
    tiny_px(ox, oy, 2, 3);
    tiny_px(ox, oy, 14, 3);

    for (int y = 4; y <= 11; ++y) {
        tiny_px(ox, oy, 2, y);
        tiny_px(ox, oy, 14, y);
    }

    /* Side pods / ears. */
    tiny_px(ox, oy, 0, 5);
    tiny_px(ox, oy, 1, 4);
    tiny_px(ox, oy, 1, 6);

    tiny_px(ox, oy, 16, 5);
    tiny_px(ox, oy, 15, 4);
    tiny_px(ox, oy, 15, 6);

    /* Eyes. */
    if (blink) {
        tiny_hline(ox, oy, 5, 6, 4);
        tiny_hline(ox, oy, 10, 11, 4);
    } else {
        tiny_px(ox, oy, 5, 4);
        tiny_px(ox, oy, 11, 4);
    }

    /* Progre's little brow / nose marks. */
    tiny_px(ox, oy, 7, 3);
    tiny_px(ox, oy, 9, 3);

    /* Mouth. */
    if (active) {
        tiny_px(ox, oy, 5, 7);
        tiny_px(ox, oy, 6, 8);
        tiny_px(ox, oy, 7, 7);
        tiny_px(ox, oy, 8, 8);
        tiny_px(ox, oy, 9, 7);
        tiny_px(ox, oy, 10, 8);
        tiny_px(ox, oy, 11, 7);

        tiny_hline(ox, oy, 5, 11, 10);
        tiny_px(ox, oy, 5, 9);
        tiny_px(ox, oy, 11, 9);
    } else {
        tiny_px(ox, oy, 5, 8);
        tiny_px(ox, oy, 6, 7);
        tiny_px(ox, oy, 7, 8);
        tiny_px(ox, oy, 8, 7);
        tiny_px(ox, oy, 9, 8);
        tiny_px(ox, oy, 10, 7);
        tiny_px(ox, oy, 11, 8);
    }

    /* Lower body. */
    tiny_px(ox, oy, 3, 12);
    tiny_px(ox, oy, 4, 13);
    tiny_hline(ox, oy, 5, 11, 14);
    tiny_px(ox, oy, 12, 13);
    tiny_px(ox, oy, 13, 12);

    /*
     * Two-frame walk. One foot extends while the other retracts.
     */
    if (step) {
        tiny_hline(ox, oy, 4, 6, 15);
        tiny_hline(ox, oy, 11, 12, 15);
    } else {
        tiny_hline(ox, oy, 4, 5, 15);
        tiny_hline(ox, oy, 10, 12, 15);
    }
}

void progre_display_show_companion(
    int x,
    bool active,
    bool blink,
    bool step)
{
    lcd_clear(COLOR_BLACK);

    /* Quiet divider below the speech-banner region. */
    lcd_fill_rect(
        0,
        BANNER_HEIGHT - 1,
        PROGRE_LCD_WIDTH,
        1,
        COLOR_DARK_GRAY
    );

    if (x < 0) {
        x = 0;
    }

    if (x > PROGRE_LCD_WIDTH - TINY_W) {
        x = PROGRE_LCD_WIDTH - TINY_W;
    }

    const int floor_y =
        PROGRE_LCD_HEIGHT - TINY_H - 5;

    draw_tiny_progre(
        x,
        floor_y,
        active,
        blink,
        step
    );
}

void progre_display_show_banner(
    const char *text,
    int scroll_x)
{
    lcd_fill_rect(
        0,
        0,
        PROGRE_LCD_WIDTH,
        BANNER_HEIGHT - 1,
        COLOR_BLACK
    );

    if (text == NULL || text[0] == '\0') {
        return;
    }

    int x = scroll_x;

    for (const char *c = text; *c; ++c) {
        if (x > -6 && x < PROGRE_LCD_WIDTH) {
            draw_char(
                x,
                4,
                *c,
                COLOR_WHITE,
                1
            );
        }
        x += 6;
    }
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
