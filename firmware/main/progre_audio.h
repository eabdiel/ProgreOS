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


/*
 * Capture mono PCM from the continuously running I2S RX path.
 *
 * The AIPI Lite microphone is presented in duplicated stereo
 * slots. This API retains the left slot only.
 *
 * Output format:
 *   16 kHz
 *   signed 16-bit
 *   little-endian
 *   mono
 */
esp_err_t progre_audio_capture_mono(
    int16_t *samples,
    size_t capacity_frames,
    size_t *frames_captured,
    uint32_t timeout_ms
);

/*
 * Play mono PCM through the continuously running I2S TX path.
 *
 * Samples are duplicated into both stereo slots. TX and RX remain
 * enabled before, during, and after playback.
 */
esp_err_t progre_audio_play_mono(
    const int16_t *samples,
    size_t frame_count
);

esp_err_t progre_audio_stream_begin(void);
esp_err_t progre_audio_stream_write(
    const int16_t *samples,
    size_t frame_count
);
esp_err_t progre_audio_stream_end(void);
