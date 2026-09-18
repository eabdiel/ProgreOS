from __future__ import annotations

import socket
import struct
from datetime import datetime, timezone

from flask import Flask, Response, jsonify, request


APP_NAME = "progre-voice-bridge"
PROTOCOL_VERSION = 1

app = Flask(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.get("/health")
def health():
    return jsonify(
        status="ready",
        bridge=APP_NAME,
        protocol=PROTOCOL_VERSION,
        timestamp=utc_now(),
    )


@app.post("/api/v1/device/hello")
def device_hello():
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify(
            status="error",
            error="JSON object required",
        ), 400

    device = payload.get("device")
    firmware = payload.get("firmware")
    capabilities = payload.get("capabilities", [])

    if not isinstance(device, str) or not device.strip():
        return jsonify(
            status="error",
            error="device is required",
        ), 400

    if not isinstance(firmware, str) or not firmware.strip():
        return jsonify(
            status="error",
            error="firmware is required",
        ), 400

    if not isinstance(capabilities, list):
        return jsonify(
            status="error",
            error="capabilities must be a list",
        ), 400

    print(
        f"[PROGRE] HELLO "
        f"device={device!r} "
        f"firmware={firmware!r} "
        f"capabilities={capabilities}",
        flush=True,
    )

    return jsonify(
        status="ready",
        message="WELCOME PROGRE",
        bridge=APP_NAME,
        protocol=PROTOCOL_VERSION,
        device=device,
        timestamp=utc_now(),
    )


@app.post("/api/v1/audio")
def device_audio():
    """
    Commissioning audio endpoint.

    Input:
        16 kHz / signed 16-bit / little-endian / mono PCM

    Output:
        Same PCM format.

    For Phase 1H the returned audio is deliberately deterministic.
    It proves the complete network/speaker path before STT, LLM,
    and TTS are introduced.
    """
    pcm = request.get_data(cache=False)

    if not pcm:
        return jsonify(
            status="error",
            error="PCM body required",
        ), 400

    if len(pcm) % 2:
        return jsonify(
            status="error",
            error="PCM body must contain complete 16-bit samples",
        ), 400

    sample_count = len(pcm) // 2
    duration = sample_count / 16000.0

    print(
        f"[PROGRE] AUDIO received "
        f"bytes={len(pcm)} "
        f"samples={sample_count} "
        f"duration={duration:.2f}s",
        flush=True,
    )

    # Deterministic acknowledgment:
    # 250 ms tone, 100 ms silence, 250 ms higher tone.
    #
    # Triangle waves are used so the test does not require numpy
    # or any other audio dependency.
    sample_rate = 16000
    amplitude = 1200

    def triangle(frequency: int, milliseconds: int):
        frames = sample_rate * milliseconds // 1000
        period = max(2, sample_rate // frequency)

        for n in range(frames):
            phase = n % period
            half = period // 2

            if phase < half:
                value = -amplitude + (2 * amplitude * phase) // half
            else:
                denom = max(1, period - half)
                value = amplitude - (
                    2 * amplitude * (phase - half)
                ) // denom

            yield max(-32768, min(32767, value))

    response_samples = []

    response_samples.extend(triangle(400, 250))
    response_samples.extend([0] * (sample_rate * 100 // 1000))
    response_samples.extend(triangle(600, 250))

    response_pcm = b"".join(
        struct.pack("<h", sample)
        for sample in response_samples
    )

    print(
        f"[PROGRE] AUDIO reply bytes={len(response_pcm)}",
        flush=True,
    )

    return Response(
        response_pcm,
        status=200,
        mimetype="application/octet-stream",
        headers={
            "X-Progre-Audio-Format": "pcm_s16le_mono_16000"
        },
    )


if __name__ == "__main__":
    hostname = socket.gethostname()

    print("=" * 60)
    print(" PROGRE VOICE BRIDGE")
    print("=" * 60)
    print(f" Host:     {hostname}")
    print(" Listen:   0.0.0.0:8765")
    print(f" Protocol: {PROTOCOL_VERSION}")
    print("=" * 60)

    app.run(
        host="0.0.0.0",
        port=8765,
        debug=False,
        threaded=True,
    )
