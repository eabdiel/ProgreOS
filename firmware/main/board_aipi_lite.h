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

/*
 * ES8311 audio codec control bus.
 *
 * Phase 1E begins with read-only I2C discovery. Audio data pins
 * and speaker amplifier control are intentionally not enabled yet.
 */
#define PROGRE_AUDIO_I2C_SCL_PIN  4
#define PROGRE_AUDIO_I2C_SDA_PIN  5
#define PROGRE_AUDIO_I2C_HZ       100000

/* ES8311 / I2S audio data path — physically mapped from AIPI Lite. */
#define PROGRE_AUDIO_MCLK_PIN      6
#define PROGRE_AUDIO_SPK_EN_PIN    9
#define PROGRE_AUDIO_DOUT_PIN     11
#define PROGRE_AUDIO_LRCLK_PIN    12
#define PROGRE_AUDIO_DIN_PIN      13
#define PROGRE_AUDIO_BCLK_PIN     14

#define PROGRE_AUDIO_SAMPLE_RATE  16000

#define PROGRE_LCD_SPI_HZ      (20 * 1000 * 1000)
