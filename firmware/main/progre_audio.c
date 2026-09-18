#include "progre_audio.h"

#include <stdint.h>

#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "driver/i2s_std.h"

#include "esp_log.h"
#include "esp_check.h"

#include "board_aipi_lite.h"

static const char *TAG = "PROGRE_AUDIO";

#define ES8311_ADDRESS_PRIMARY    0x18
#define ES8311_ADDRESS_SECONDARY  0x19

static i2c_master_bus_handle_t s_i2c_bus = NULL;
static i2c_master_dev_handle_t s_codec = NULL;
static i2s_chan_handle_t s_tx = NULL;
static i2s_chan_handle_t s_rx = NULL;

static uint8_t s_codec_address = 0;

static esp_err_t probe_address(uint8_t address)
{
    return i2c_master_probe(s_i2c_bus, address, 100);
}

static esp_err_t codec_write(uint8_t reg, uint8_t value)
{
    uint8_t payload[2] = { reg, value };
    return i2c_master_transmit(s_codec, payload, sizeof(payload), 100);
}

static esp_err_t codec_write_checked(uint8_t reg, uint8_t value)
{
    esp_err_t err = codec_write(reg, value);

    if (err != ESP_OK) {
        ESP_LOGE(TAG,
                 "ES8311 write failed reg=0x%02x value=0x%02x: %s",
                 reg, value, esp_err_to_name(err));
    }

    return err;
}

esp_err_t progre_audio_probe_codec(void)
{
    ESP_LOGI(TAG, "Initializing ES8311 control bus");
    ESP_LOGI(TAG,
             "I2C SDA=GPIO%d SCL=GPIO%d frequency=%d Hz",
             PROGRE_AUDIO_I2C_SDA_PIN,
             PROGRE_AUDIO_I2C_SCL_PIN,
             PROGRE_AUDIO_I2C_HZ);

    if (s_i2c_bus == NULL) {
        i2c_master_bus_config_t bus_config = {
            .i2c_port = I2C_NUM_0,
            .sda_io_num = PROGRE_AUDIO_I2C_SDA_PIN,
            .scl_io_num = PROGRE_AUDIO_I2C_SCL_PIN,
            .clk_source = I2C_CLK_SRC_DEFAULT,
            .glitch_ignore_cnt = 7,
            .flags.enable_internal_pullup = true,
        };

        esp_err_t err =
            i2c_new_master_bus(&bus_config, &s_i2c_bus);

        if (err != ESP_OK) {
            ESP_LOGE(TAG,
                     "Unable to initialize I2C bus: %s",
                     esp_err_to_name(err));
            return err;
        }
    }

    ESP_LOGI(TAG, "Probing expected ES8311 addresses");

    esp_err_t err = probe_address(ES8311_ADDRESS_PRIMARY);

    if (err == ESP_OK) {
        s_codec_address = ES8311_ADDRESS_PRIMARY;
    } else {
        err = probe_address(ES8311_ADDRESS_SECONDARY);

        if (err == ESP_OK) {
            s_codec_address = ES8311_ADDRESS_SECONDARY;
        } else {
            ESP_LOGE(TAG,
                     "ES8311 not detected at 0x18 or 0x19");
            return ESP_ERR_NOT_FOUND;
        }
    }

    ESP_LOGI(TAG,
             "ES8311 detected at I2C address 0x%02x",
             s_codec_address);

    if (s_codec == NULL) {
        i2c_device_config_t dev_cfg = {
            .dev_addr_length = I2C_ADDR_BIT_LEN_7,
            .device_address = s_codec_address,
            .scl_speed_hz = PROGRE_AUDIO_I2C_HZ,
        };

        err = i2c_master_bus_add_device(
            s_i2c_bus,
            &dev_cfg,
            &s_codec
        );

        if (err != ESP_OK) {
            ESP_LOGE(TAG,
                     "Unable to attach ES8311 device: %s",
                     esp_err_to_name(err));
            return err;
        }
    }

    return ESP_OK;
}

esp_err_t progre_audio_init_microphone(void)
{
    if (s_codec == NULL) {
        ESP_LOGE(TAG,
                 "Microphone init requested before codec discovery");
        return ESP_ERR_INVALID_STATE;
    }

    /*
     * Keep speaker power amplifier OFF during microphone bring-up.
     */
    gpio_config_t amp_cfg = {
        .pin_bit_mask = 1ULL << PROGRE_AUDIO_SPK_EN_PIN,
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };

    ESP_RETURN_ON_ERROR(
        gpio_config(&amp_cfg),
        TAG,
        "Unable to configure speaker amplifier gate"
    );

    ESP_RETURN_ON_ERROR(
        gpio_set_level(PROGRE_AUDIO_SPK_EN_PIN, 0),
        TAG,
        "Unable to disable speaker amplifier"
    );

    ESP_LOGI(TAG, "Speaker amplifier held OFF on GPIO%d",
             PROGRE_AUDIO_SPK_EN_PIN);

    /*
     * Allocate RX-only I2S channel first.
     * This starts MCLK after standard-mode initialization; BCLK/WS
     * begin when the RX channel is enabled.
     */
    i2s_chan_config_t chan_cfg =
        I2S_CHANNEL_DEFAULT_CONFIG(
            I2S_NUM_0,
            I2S_ROLE_MASTER
        );

    ESP_RETURN_ON_ERROR(
        i2s_new_channel(&chan_cfg, &s_tx, &s_rx),
        TAG,
        "Unable to allocate paired I2S TX/RX channels"
    );

    i2s_std_config_t std_cfg = {
        .clk_cfg =
            I2S_STD_CLK_DEFAULT_CONFIG(
                PROGRE_AUDIO_SAMPLE_RATE
            ),

        /*
         * The ES8311 reference configuration uses ordinary I2S
         * framing with 16-bit samples.
         *
         * Stereo framing is intentional here: it preserves the
         * expected 64*Fs BCLK relationship while we consume only
         * the codec's ADC slot.
         */
        .slot_cfg =
            I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
                I2S_DATA_BIT_WIDTH_16BIT,
                I2S_SLOT_MODE_STEREO
            ),

        .gpio_cfg = {
            .mclk = PROGRE_AUDIO_MCLK_PIN,
            .bclk = PROGRE_AUDIO_BCLK_PIN,
            .ws   = PROGRE_AUDIO_LRCLK_PIN,
            .dout = PROGRE_AUDIO_DOUT_PIN,
            .din  = PROGRE_AUDIO_DIN_PIN,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv   = false,
            },
        },
    };

    ESP_RETURN_ON_ERROR(
        i2s_channel_init_std_mode(s_rx, &std_cfg),
        TAG,
        "Unable to initialize I2S RX standard mode"
    );

    ESP_RETURN_ON_ERROR(
        i2s_channel_init_std_mode(s_tx, &std_cfg),
        TAG,
        "Unable to initialize I2S TX standard mode"
    );

    ESP_LOGI(TAG,
             "I2S TX/RX configured: %d Hz / 16-bit / MCLK=%d BCLK=%d LRCLK=%d DIN=%d DOUT=%d",
             PROGRE_AUDIO_SAMPLE_RATE,
             PROGRE_AUDIO_MCLK_PIN,
             PROGRE_AUDIO_BCLK_PIN,
             PROGRE_AUDIO_LRCLK_PIN,
             PROGRE_AUDIO_DIN_PIN,
             PROGRE_AUDIO_DOUT_PIN);

    /*
     * ES8311 sequence derived from the physically mapped AIPI Lite
     * reference implementation.
     *
     * Clocking:
     *   16 kHz, BCLK-derived codec clock.
     */
    static const uint8_t reset_sequence[][2] = {
        {0x00, 0x1F},
        {0x00, 0x00},
    };

    static const uint8_t clock_sequence[][2] = {
        {0x01, 0x9F},
        {0x02, 0x10},
        {0x03, 0x10},
        {0x04, 0x20},
        {0x05, 0x00},
        {0x06, 0x03},
        {0x07, 0x00},
        {0x08, 0xFF},
    };

    static const uint8_t format_sequence[][2] = {
        {0x09, 0x0C},
        {0x0A, 0x0C},
    };

    static const uint8_t input_sequence[][2] = {
        {0x14, 0x1A},
        {0x15, 0x40},
        {0x16, 0x24},
        {0x17, 0xBF},
        {0x1C, 0x6A},
    };

    static const uint8_t power_sequence[][2] = {
        {0x0D, 0x01},
        {0x0E, 0x02},
        {0x00, 0x80},
    };

    /*
     * ES8311 DAC path.
     * Keep DAC muted during initialization. The external amplifier
     * remains disabled until an explicit playback request.
     */
    static const uint8_t output_sequence[][2] = {
        {0x32, 0xBF},
        {0x12, 0x00},
        {0x13, 0x10},
        {0x31, 0x60},
        {0x37, 0x08},
    };

#define WRITE_SEQUENCE(seq)                                      \
    do {                                                         \
        for (size_t i = 0; i < sizeof(seq) / sizeof(seq[0]); ++i) { \
            ESP_RETURN_ON_ERROR(                                 \
                codec_write_checked(seq[i][0], seq[i][1]),       \
                TAG,                                             \
                "ES8311 sequence failed"                         \
            );                                                   \
        }                                                        \
    } while (0)

    WRITE_SEQUENCE(reset_sequence);
    WRITE_SEQUENCE(clock_sequence);
    WRITE_SEQUENCE(format_sequence);
    WRITE_SEQUENCE(input_sequence);
    WRITE_SEQUENCE(output_sequence);
    WRITE_SEQUENCE(power_sequence);

#undef WRITE_SEQUENCE

    ESP_LOGI(TAG, "ES8311 microphone registers initialized");

    /*
     * The ESP32-S3 I2S controller is operating as a paired
     * full-duplex TX/RX interface. Start both channel halves so
     * the shared codec clock domain remains active for capture.
     *
     * Speaker output remains electrically silent here:
     *   - ES8311 DAC is still muted
     *   - GPIO9 amplifier enable remains LOW
     */
    ESP_RETURN_ON_ERROR(
        i2s_channel_enable(s_tx),
        TAG,
        "Unable to enable paired I2S TX"
    );

    ESP_RETURN_ON_ERROR(
        i2s_channel_enable(s_rx),
        TAG,
        "Unable to enable paired I2S RX"
    );

    ESP_LOGI(TAG,
             "Paired I2S TX/RX channels RUNNING; speaker remains muted");
    ESP_LOGI(TAG, "Microphone capture path READY");

    return ESP_OK;
}

esp_err_t progre_audio_measure_microphone(void)
{
    if (s_rx == NULL) {
        return ESP_ERR_INVALID_STATE;
    }

    /*
     * 100 ms at 16 kHz, stereo-framed 16-bit input.
     * We inspect both slots separately so physical validation tells
     * us which slot contains the ES8311 ADC stream.
     */
    enum {
        FRAME_COUNT = PROGRE_AUDIO_SAMPLE_RATE / 10
    };

    static int16_t samples[FRAME_COUNT * 2];
    size_t bytes_read = 0;

    esp_err_t err = i2s_channel_read(
        s_rx,
        samples,
        sizeof(samples),
        &bytes_read,
        250
    );

    if (err != ESP_OK) {
        ESP_LOGW(TAG,
                 "Microphone read failed: %s",
                 esp_err_to_name(err));
        return err;
    }

    size_t sample_count = bytes_read / sizeof(int16_t);
    size_t frame_count = sample_count / 2;

    if (frame_count == 0) {
        ESP_LOGW(TAG, "Microphone returned zero frames");
        return ESP_ERR_INVALID_SIZE;
    }

    int32_t peak_left = 0;
    int32_t peak_right = 0;

    uint64_t energy_left = 0;
    uint64_t energy_right = 0;

    for (size_t i = 0; i < frame_count; ++i) {
        int32_t left = samples[i * 2];
        int32_t right = samples[i * 2 + 1];

        int32_t abs_left = left < 0 ? -left : left;
        int32_t abs_right = right < 0 ? -right : right;

        if (abs_left > peak_left) {
            peak_left = abs_left;
        }

        if (abs_right > peak_right) {
            peak_right = abs_right;
        }

        energy_left += (uint64_t)(left * left);
        energy_right += (uint64_t)(right * right);
    }

    /*
     * Mean-square energy avoids floating-point/sqrt dependencies
     * while still giving us a strong silence-vs-speech signal.
     */
    uint64_t mean_square_left =
        energy_left / frame_count;

    uint64_t mean_square_right =
        energy_right / frame_count;

    ESP_LOGI(TAG,
             "MIC frames=%u bytes=%u | LEFT peak=%ld mean_sq=%llu | RIGHT peak=%ld mean_sq=%llu",
             (unsigned)frame_count,
             (unsigned)bytes_read,
             (long)peak_left,
             (unsigned long long)mean_square_left,
             (long)peak_right,
             (unsigned long long)mean_square_right);

    return ESP_OK;
}


esp_err_t progre_audio_test_speaker(void)
{
    if (s_codec == NULL || s_tx == NULL) {
        ESP_LOGE(TAG, "Speaker test requested before audio initialization");
        return ESP_ERR_INVALID_STATE;
    }

    /*
     * Conservative hardware-validation chirp.
     *
     * The paired I2S TX/RX transport is already RUNNING and remains
     * running before, during, and after playback. Speaker audibility
     * is controlled only by the ES8311 DAC mute and GPIO9 amplifier.
     *
     * 16 kHz, 16-bit stereo frames carrying duplicated mono.
     * Integer triangle wave avoids floating-point/libm dependency.
     */
    enum {
        FRAMES_PER_CHUNK = 160,
        CHUNKS = 25,
        PERIOD_FRAMES = 40,
        AMPLITUDE = 1200
    };

    static int16_t samples[FRAMES_PER_CHUNK * 2];

    esp_err_t result = ESP_OK;

    ESP_LOGI(TAG, "Speaker test starting on running duplex transport");

    /*
     * Prime the running TX path with silence while both the DAC
     * and external amplifier are still inaudible.
     */
    for (size_t i = 0; i < FRAMES_PER_CHUNK * 2; ++i) {
        samples[i] = 0;
    }

    size_t bytes_written = 0;

    result = i2s_channel_write(
        s_tx,
        samples,
        sizeof(samples),
        &bytes_written,
        250
    );

    if (result != ESP_OK) {
        ESP_LOGE(TAG,
                 "Unable to prime speaker TX: %s",
                 esp_err_to_name(result));
        goto cleanup;
    }

    result = codec_write_checked(0x31, 0x00);
    if (result != ESP_OK) {
        ESP_LOGE(TAG,
                 "Unable to unmute ES8311 DAC: %s",
                 esp_err_to_name(result));
        goto cleanup;
    }

    result = gpio_set_level(PROGRE_AUDIO_SPK_EN_PIN, 1);
    if (result != ESP_OK) {
        ESP_LOGE(TAG,
                 "Unable to enable speaker amplifier: %s",
                 esp_err_to_name(result));
        goto cleanup;
    }

    for (int chunk = 0; chunk < CHUNKS; ++chunk) {
        for (int frame = 0; frame < FRAMES_PER_CHUNK; ++frame) {
            int phase =
                (chunk * FRAMES_PER_CHUNK + frame) % PERIOD_FRAMES;

            int32_t sample;

            if (phase < PERIOD_FRAMES / 2) {
                sample =
                    -AMPLITUDE +
                    (4 * AMPLITUDE * phase) / PERIOD_FRAMES;
            } else {
                sample =
                    AMPLITUDE -
                    (4 * AMPLITUDE *
                     (phase - PERIOD_FRAMES / 2)) /
                    PERIOD_FRAMES;
            }

            samples[frame * 2] = (int16_t)sample;
            samples[frame * 2 + 1] = (int16_t)sample;
        }

        bytes_written = 0;

        result = i2s_channel_write(
            s_tx,
            samples,
            sizeof(samples),
            &bytes_written,
            250
        );

        if (result != ESP_OK) {
            ESP_LOGE(TAG,
                     "Speaker TX failed: %s",
                     esp_err_to_name(result));
            goto cleanup;
        }
    }

    /*
     * End with one silent chunk before closing the analog path.
     * The digital duplex transport itself stays running.
     */
    for (size_t i = 0; i < FRAMES_PER_CHUNK * 2; ++i) {
        samples[i] = 0;
    }

    bytes_written = 0;

    result = i2s_channel_write(
        s_tx,
        samples,
        sizeof(samples),
        &bytes_written,
        250
    );

    if (result != ESP_OK) {
        ESP_LOGE(TAG,
                 "Unable to write trailing speaker silence: %s",
                 esp_err_to_name(result));
    }

cleanup:
    /*
     * Best-effort safety cleanup. Always attempt both operations,
     * even if playback or the first cleanup action failed.
     */
    esp_err_t amp_off_err =
        gpio_set_level(PROGRE_AUDIO_SPK_EN_PIN, 0);

    esp_err_t mute_err =
        codec_write_checked(0x31, 0x60);

    if (result == ESP_OK && amp_off_err != ESP_OK) {
        result = amp_off_err;
    }

    if (result == ESP_OK && mute_err != ESP_OK) {
        result = mute_err;
    }

    if (amp_off_err != ESP_OK) {
        ESP_LOGE(TAG,
                 "Unable to disable speaker amplifier: %s",
                 esp_err_to_name(amp_off_err));
    }

    if (mute_err != ESP_OK) {
        ESP_LOGE(TAG,
                 "Unable to mute ES8311 DAC: %s",
                 esp_err_to_name(mute_err));
    }

    if (result == ESP_OK) {
        ESP_LOGI(TAG,
                 "Speaker test complete; duplex I2S remains RUNNING");
    } else {
        ESP_LOGE(TAG,
                 "Speaker test ended with error: %s",
                 esp_err_to_name(result));
    }

    return result;
}

/*
 * ----------------------------------------------------------------
 * Progre application audio primitives
 * ----------------------------------------------------------------
 *
 * These functions intentionally reuse the already-running paired
 * I2S transport established by progre_audio_init_microphone().
 *
 * Neither function disables s_tx or s_rx.
 */

esp_err_t progre_audio_capture_mono(
    int16_t *samples,
    size_t capacity_frames,
    size_t *frames_captured,
    uint32_t timeout_ms)
{
    if (samples == NULL ||
        frames_captured == NULL ||
        capacity_frames == 0) {
        return ESP_ERR_INVALID_ARG;
    }

    if (s_rx == NULL) {
        return ESP_ERR_INVALID_STATE;
    }

    enum {
        CAPTURE_CHUNK_FRAMES = 320
    };

    int16_t stereo[CAPTURE_CHUNK_FRAMES * 2];

    size_t requested_frames =
        capacity_frames < CAPTURE_CHUNK_FRAMES
            ? capacity_frames
            : CAPTURE_CHUNK_FRAMES;

    size_t bytes_read = 0;

    esp_err_t err = i2s_channel_read(
        s_rx,
        stereo,
        requested_frames * 2 * sizeof(int16_t),
        &bytes_read,
        timeout_ms
    );

    if (err != ESP_OK) {
        *frames_captured = 0;
        return err;
    }

    size_t stereo_samples =
        bytes_read / sizeof(int16_t);

    size_t frames =
        stereo_samples / 2;

    if (frames > capacity_frames) {
        frames = capacity_frames;
    }

    for (size_t i = 0; i < frames; ++i) {
        samples[i] = stereo[i * 2];
    }

    *frames_captured = frames;

    return ESP_OK;
}


esp_err_t progre_audio_play_mono(
    const int16_t *samples,
    size_t frame_count)
{
    if (samples == NULL || frame_count == 0) {
        return ESP_ERR_INVALID_ARG;
    }

    if (s_codec == NULL || s_tx == NULL) {
        ESP_LOGE(
            TAG,
            "PCM playback requested before audio initialization"
        );

        return ESP_ERR_INVALID_STATE;
    }

    enum {
        PLAYBACK_CHUNK_FRAMES = 320
    };

    int16_t stereo[PLAYBACK_CHUNK_FRAMES * 2];

    esp_err_t result = ESP_OK;
    size_t bytes_written = 0;

    /*
     * Prime the already-running TX path with silence while the
     * analog output remains muted.
     */
    for (size_t i = 0;
         i < PLAYBACK_CHUNK_FRAMES * 2;
         ++i) {
        stereo[i] = 0;
    }

    result = i2s_channel_write(
        s_tx,
        stereo,
        sizeof(stereo),
        &bytes_written,
        250
    );

    if (result != ESP_OK) {
        ESP_LOGE(
            TAG,
            "Unable to prime PCM playback: %s",
            esp_err_to_name(result)
        );

        goto cleanup;
    }

    result = codec_write_checked(0x31, 0x00);

    if (result != ESP_OK) {
        goto cleanup;
    }

    result =
        gpio_set_level(PROGRE_AUDIO_SPK_EN_PIN, 1);

    if (result != ESP_OK) {
        ESP_LOGE(
            TAG,
            "Unable to enable speaker amplifier: %s",
            esp_err_to_name(result)
        );

        goto cleanup;
    }

    ESP_LOGI(
        TAG,
        "PCM playback starting: %u mono frames",
        (unsigned)frame_count
    );

    size_t offset = 0;

    while (offset < frame_count) {

        size_t chunk =
            frame_count - offset;

        if (chunk > PLAYBACK_CHUNK_FRAMES) {
            chunk = PLAYBACK_CHUNK_FRAMES;
        }

        for (size_t i = 0; i < chunk; ++i) {
            int16_t sample = samples[offset + i];

            stereo[i * 2] = sample;
            stereo[i * 2 + 1] = sample;
        }

        bytes_written = 0;

        result = i2s_channel_write(
            s_tx,
            stereo,
            chunk * 2 * sizeof(int16_t),
            &bytes_written,
            500
        );

        if (result != ESP_OK) {
            ESP_LOGE(
                TAG,
                "PCM speaker TX failed: %s",
                esp_err_to_name(result)
            );

            goto cleanup;
        }

        offset += chunk;
    }

    /*
     * Trailing silence before closing the analog output.
     */
    for (size_t i = 0;
         i < PLAYBACK_CHUNK_FRAMES * 2;
         ++i) {
        stereo[i] = 0;
    }

    bytes_written = 0;

    result = i2s_channel_write(
        s_tx,
        stereo,
        sizeof(stereo),
        &bytes_written,
        250
    );

cleanup:

    /*
     * Always make the physical speaker inaudible again.
     * The digital TX/RX channels remain RUNNING.
     */
    {
        esp_err_t amp_err =
            gpio_set_level(
                PROGRE_AUDIO_SPK_EN_PIN,
                0
            );

        esp_err_t mute_err =
            codec_write_checked(0x31, 0x60);

        if (result == ESP_OK &&
            amp_err != ESP_OK) {
            result = amp_err;
        }

        if (result == ESP_OK &&
            mute_err != ESP_OK) {
            result = mute_err;
        }
    }

    if (result == ESP_OK) {
        ESP_LOGI(
            TAG,
            "PCM playback complete; duplex I2S remains RUNNING"
        );
    }

    return result;
}


esp_err_t progre_audio_stream_begin(void)
{
    if (s_tx == NULL) {
        ESP_LOGE(TAG, "Streaming playback unavailable: TX not initialized");
        return ESP_ERR_INVALID_STATE;
    }

    /*
     * Duplex invariant:
     * TX/RX remain RUNNING at all times.
     *
     * Playback is controlled only through codec mute and amplifier gate.
     */
    ESP_RETURN_ON_ERROR(
        codec_write_checked(0x31, 0x00),
        TAG,
        "Unable to unmute DAC for streaming"
    );

    gpio_set_level(PROGRE_AUDIO_SPK_EN_PIN, 1);

    ESP_LOGI(TAG, "PCM streaming playback started");
    return ESP_OK;
}


esp_err_t progre_audio_stream_write(
    const int16_t *samples,
    size_t frame_count
)
{
    if (samples == NULL || frame_count == 0) {
        return ESP_OK;
    }

    if (s_tx == NULL) {
        return ESP_ERR_INVALID_STATE;
    }

    /*
     * Network audio is mono.
     * ES8311/I2S transport remains stereo, so duplicate each mono
     * frame into L/R without buffering the whole response.
     */
    enum {
        STREAM_CHUNK_FRAMES = 256
    };

    int16_t stereo[STREAM_CHUNK_FRAMES * 2];

    size_t offset = 0;

    while (offset < frame_count) {
        size_t remaining = frame_count - offset;
        size_t chunk = remaining;

        if (chunk > STREAM_CHUNK_FRAMES) {
            chunk = STREAM_CHUNK_FRAMES;
        }

        for (size_t i = 0; i < chunk; ++i) {
            int16_t sample = samples[offset + i];
            stereo[i * 2] = sample;
            stereo[i * 2 + 1] = sample;
        }

        size_t bytes_written = 0;

        esp_err_t err = i2s_channel_write(
            s_tx,
            stereo,
            chunk * 2 * sizeof(int16_t),
            &bytes_written,
            500
        );

        if (err != ESP_OK) {
            ESP_LOGE(
                TAG,
                "Streaming I2S write failed: %s",
                esp_err_to_name(err)
            );
            return err;
        }

        if (bytes_written != chunk * 2 * sizeof(int16_t)) {
            ESP_LOGE(
                TAG,
                "Streaming I2S short write: %u/%u bytes",
                (unsigned)bytes_written,
                (unsigned)(chunk * 2 * sizeof(int16_t))
            );
            return ESP_FAIL;
        }

        offset += chunk;
    }

    return ESP_OK;
}


esp_err_t progre_audio_stream_end(void)
{
    if (s_tx == NULL) {
        return ESP_ERR_INVALID_STATE;
    }

    /*
     * Push a small silence tail before muting to avoid clipping the
     * final phoneme and to leave the codec in a quiet state.
     */
    int16_t silence[160 * 2] = {0};
    size_t bytes_written = 0;

    esp_err_t err = i2s_channel_write(
        s_tx,
        silence,
        sizeof(silence),
        &bytes_written,
        500
    );

    gpio_set_level(PROGRE_AUDIO_SPK_EN_PIN, 0);

    esp_err_t mute_err =
        codec_write_checked(0x31, 0x60);

    if (err != ESP_OK) {
        return err;
    }

    if (mute_err != ESP_OK) {
        return mute_err;
    }

    ESP_LOGI(
        TAG,
        "PCM streaming playback complete; duplex I2S remains RUNNING"
    );

    return ESP_OK;
}
