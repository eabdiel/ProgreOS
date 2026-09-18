#pragma once

#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

esp_err_t progre_bridge_init(void);

/*
 * Send mono 16 kHz signed-16 PCM to the Progre Voice Bridge
 * and receive mono PCM in the same format.
 */
esp_err_t progre_bridge_exchange_audio(
    const int16_t *request_samples,
    size_t request_frames,
    int16_t *response_samples,
    size_t response_capacity_frames,
    size_t *response_frames
);

esp_err_t progre_bridge_exchange_audio_stream(
    const int16_t *request_samples,
    size_t request_frames
);
