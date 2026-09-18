from __future__ import annotations

import base64
import subprocess
import tempfile
import wave
from pathlib import Path

import socket
import struct
from datetime import datetime, timezone

from flask import Flask, Response, jsonify, request

from progre_config import load_config
from progre_runtime import discover as runtime_discover


APP_NAME = "progre-voice-bridge"
PROTOCOL_VERSION = 1

app = Flask(__name__)


PROGRE_OLLAMA_URL = "http://127.0.0.1:11434/api/generate"

PROGRE_SYSTEM_PROMPT = """
You are Progre, a small physical desktop companion created as
part of the ProgreTech project.

You are speaking directly with Edwin.

Be warm, curious, concise, and conversational.
You may occasionally be playful.
Keep ordinary spoken responses to one or two short sentences.

You are also intended to become a Japanese-learning companion,
but do not force Japanese into unrelated conversations.

Never describe yourself as a generic AI assistant.
Your name is Progre.
""".strip()



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


def _pcm_to_wav(pcm: bytes, path: str):
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(pcm)


def _wav_to_pcm_16k_mono(wav_path):
    cfg = load_config()

    pitch_semitones = float(
        cfg["pitch_semitones"]
    )

    volume = float(
        cfg["volume"]
    )

    pitch_factor = 2.0 ** (
        pitch_semitones / 12.0
    )

    tempo_factor = 1.0 / pitch_factor

    with wave.open(str(wav_path), "rb") as source:
        source_rate = source.getframerate()

    filter_chain = (
        f"asetrate={source_rate}*{pitch_factor:.8f},"
        f"aresample=16000,"
        f"atempo={tempo_factor:.8f},"
        f"volume={volume:.4f}"
    )

    with tempfile.NamedTemporaryFile(
        suffix=".raw",
        delete=False,
    ) as raw_file:
        raw_path = Path(raw_file.name)

    try:
        process = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(wav_path),
                "-af",
                filter_chain,
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "s16le",
                str(raw_path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if process.returncode != 0:
            raise RuntimeError(
                "ffmpeg voice processing failed: "
                + process.stderr.strip()
            )

        return raw_path.read_bytes()

    finally:
        raw_path.unlink(
            missing_ok=True
        )


def _transcribe(pcm: bytes, workdir: str) -> str:
    input_wav = str(Path(workdir) / "input.wav")
    output_base = str(Path(workdir) / "whisper")

    _pcm_to_wav(pcm, input_wav)

    runtime = runtime_discover()
    whisper = runtime.get("whisper")
    whisper_model = runtime.get("whisper_model")
    if not whisper or not whisper_model:
        raise RuntimeError("Whisper runtime/model missing. Open Progre Cockpit → Local Runtime.")

    result = subprocess.run(
        [
            whisper,
            "-m", whisper_model,
            "-f", input_wav,
            "-otxt",
            "-of", output_base,
            "-nt",
            "-np",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Whisper failed: " +
            result.stderr[-1000:]
        )

    transcript_path = Path(output_base + ".txt")

    if not transcript_path.exists():
        raise RuntimeError(
            "Whisper did not produce transcript"
        )

    return transcript_path.read_text().strip()


def _ask_progre(transcript: str) -> str:
    cfg = load_config()
    import json
    import urllib.request

    payload = json.dumps(
        {
            "model": cfg["model"],
            "system": PROGRE_SYSTEM_PROMPT,
            "prompt": transcript,
            "stream": False,
            "think": False,
            "keep_alive": "10m",
            "options": {
                "temperature": cfg["temperature"],
                "num_predict": cfg["max_tokens"]
            }
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        PROGRE_OLLAMA_URL,
        data=payload,
        headers={
            "Content-Type": "application/json"
        },
        method="POST",
    )

    with urllib.request.urlopen(
        req,
        timeout=90
    ) as response:
        data = json.loads(
            response.read().decode("utf-8")
        )

    answer = data.get("response", "").strip()

    if not answer:
        raise RuntimeError(
            "Ollama returned an empty response"
        )

    return answer


def _synthesize(text: str, workdir: str) -> bytes:
    cfg = load_config()
    output_wav = str(Path(workdir) / "response.wav")

    runtime = runtime_discover()
    piper = runtime.get("piper")
    voices = [Path(v) for v in runtime.get("voices", [])]
    voice = next((v for v in voices if v.name == cfg["voice"]), None)
    if not piper or voice is None:
        raise RuntimeError("Piper runtime/voice missing. Open Progre Cockpit → Local Runtime.")

    result = subprocess.run(
        [
            piper,
            "--model", str(voice),
            "--output_file", output_wav,
        ],
        input=text + "\n",
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Piper failed: " +
            result.stderr[-1000:]
        )

    if not Path(output_wav).exists():
        raise RuntimeError(
            "Piper did not produce response.wav"
        )

    return _wav_to_pcm_16k_mono(output_wav)



@app.post("/api/v1/audio")
def device_audio():
    """
    Progre conversational voice endpoint.

    Input/output:
        16 kHz / signed 16-bit / little-endian / mono PCM
    """
    pcm = request.get_data(cache=False)

    if not pcm or len(pcm) % 2:
        return jsonify(
            status="error",
            error="valid signed-16 PCM body required",
        ), 400

    print(
        f"[PROGRE] VOICE received bytes={len(pcm)}",
        flush=True,
    )

    try:
        with tempfile.TemporaryDirectory(
            prefix="progre-voice-"
        ) as workdir:

            transcript = _transcribe(
                pcm,
                workdir
            )

            print(
                f"[PROGRE] HEARD: {transcript}",
                flush=True,
            )

            if not transcript:
                raise RuntimeError(
                    "No speech recognized"
                )

            answer = _ask_progre(transcript)

            print(
                f"[PROGRE] SAYS: {answer}",
                flush=True,
            )

            response_pcm = _synthesize(
                answer,
                workdir
            )

        print(
            f"[PROGRE] VOICE reply bytes="
            f"{len(response_pcm)}",
            flush=True,
        )

        return Response(
            response_pcm,
            status=200,
            mimetype="application/octet-stream",
            headers={
                "X-Progre-Audio-Format":
                    "pcm_s16le_mono_16000",
                "X-Progre-Text-B64":
                    base64.b64encode(
                        answer.encode("utf-8")
                    ).decode("ascii"),
            },
        )

    except Exception as exc:
        print(
            f"[PROGRE] VOICE ERROR: {exc}",
            flush=True,
        )

        return jsonify(
            status="error",
            error=str(exc),
        ), 500


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
