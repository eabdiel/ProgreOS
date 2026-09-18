from __future__ import annotations

import socket
from datetime import datetime, timezone

from flask import Flask, jsonify, request


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
