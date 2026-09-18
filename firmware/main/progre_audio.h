#pragma once

#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

/*
 * Initialize the AIPI Lite audio-control I2C bus and perform
 * non-destructive ES8311 address discovery.
 */
esp_err_t progre_audio_probe_codec(void);

/*
 * Initialize the ES8311 audio path and paired 16 kHz, 16-bit
 * I2S TX/RX transport.
 *
 * Both channel halves remain running continuously. Microphone
 * capture is available immediately while the ES8311 DAC remains
 * muted and the external speaker amplifier remains disabled.
 */
esp_err_t progre_audio_init_microphone(void);

/*
 * Capture a short microphone window and report statistics.
 * Intended only as a hardware-validation primitive.
 */
esp_err_t progre_audio_measure_microphone(void);


/*
 * Play a short, low-level hardware-validation chirp through
 * the ES8311 DAC and onboard speaker amplifier.
 */
esp_err_t progre_audio_test_speaker(void);
