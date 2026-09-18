#pragma once

#define PROGRE_LCD_WIDTH       128
#define PROGRE_LCD_HEIGHT      128

#define PROGRE_LCD_PIN_SCLK    16
#define PROGRE_LCD_PIN_MOSI    17
#define PROGRE_LCD_PIN_DC       7
#define PROGRE_LCD_PIN_CS      15
#define PROGRE_LCD_PIN_RST     18
#define PROGRE_LCD_PIN_BL       3

/*
 * AIPI Lite right-side function / Talk button.
 * Active-low with internal pull-up.
 */
#define PROGRE_BUTTON_TALK_PIN  42

#define PROGRE_LCD_SPI_HZ      (20 * 1000 * 1000)
