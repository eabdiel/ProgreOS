from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
WHISPER_DIR = RUNTIME / "whisper"
MODEL_DIR = RUNTIME / "models"
PIPER_DIR = RUNTIME / "piper"
VOICE_DIR = RUNTIME / "voices"


def first_existing(*paths):
    for candidate in paths:
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_file():
            return path
    return None


def discover():
    whisper = first_existing(
        WHISPER_DIR / "whisper-cli",
        WHISPER_DIR / "build/bin/whisper-cli",
        shutil.which("whisper-cli") or "",
    )
    whisper_model = first_existing(
        MODEL_DIR / "ggml-base.en.bin",
        WHISPER_DIR / "models/ggml-base.en.bin",
    )
    piper = first_existing(
        PIPER_DIR / "piper",
        PIPER_DIR / "piper/piper",
        shutil.which("piper") or "",
    )
    voices = sorted(VOICE_DIR.glob("*.onnx"))
    return {
        "whisper": str(whisper) if whisper else None,
        "whisper_model": str(whisper_model) if whisper_model else None,
        "ollama": shutil.which("ollama"),
        "piper": str(piper) if piper else None,
        "ffmpeg": shutil.which("ffmpeg"),
        "voices": [str(v) for v in voices],
    }


def readiness():
    d = discover()
    return {
        "whisper": bool(d["whisper"]),
        "whisper_model": bool(d["whisper_model"]),
        "ollama": bool(d["ollama"]),
        "piper": bool(d["piper"]),
        "ffmpeg": bool(d["ffmpeg"]),
        "voice": bool(d["voices"]),
    }
