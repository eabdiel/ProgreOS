from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import RLock


BASE_DIR = Path(__file__).resolve().parent

CONFIG_PATH = Path(
    os.environ.get(
        "PROGRE_CONFIG_PATH",
        BASE_DIR / "progre_config.local.json",
    )
)

LOCK = RLock()


DEFAULT_CONFIG = {
    "model": "qwen3.5:2b",
    "voice": "en_US-arctic-medium.onnx",
    "pitch_semitones": 2.0,
    "volume": 0.90,
    "temperature": 0.50,
    "max_tokens": 60,
}


def _coerce(config: dict) -> dict:
    result = dict(DEFAULT_CONFIG)

    if isinstance(config, dict):
        result.update(config)

    result["model"] = str(
        result.get("model", DEFAULT_CONFIG["model"])
    ).strip()

    result["voice"] = str(
        result.get("voice", DEFAULT_CONFIG["voice"])
    ).strip()

    result["pitch_semitones"] = max(
        -6.0,
        min(
            6.0,
            float(
                result.get(
                    "pitch_semitones",
                    DEFAULT_CONFIG["pitch_semitones"],
                )
            ),
        ),
    )

    result["volume"] = max(
        0.05,
        min(
            2.0,
            float(
                result.get(
                    "volume",
                    DEFAULT_CONFIG["volume"],
                )
            ),
        ),
    )

    result["temperature"] = max(
        0.0,
        min(
            2.0,
            float(
                result.get(
                    "temperature",
                    DEFAULT_CONFIG["temperature"],
                )
            ),
        ),
    )

    result["max_tokens"] = max(
        20,
        min(
            400,
            int(
                result.get(
                    "max_tokens",
                    DEFAULT_CONFIG["max_tokens"],
                )
            ),
        ),
    )

    return result


def load_config() -> dict:
    with LOCK:
        if not CONFIG_PATH.exists():
            return dict(DEFAULT_CONFIG)

        try:
            raw = json.loads(
                CONFIG_PATH.read_text()
            )
        except Exception:
            return dict(DEFAULT_CONFIG)

        return _coerce(raw)


def save_config(config: dict) -> dict:
    clean = _coerce(config)

    CONFIG_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with LOCK:
        fd, tmp_name = tempfile.mkstemp(
            prefix="progre-config-",
            suffix=".json",
            dir=str(CONFIG_PATH.parent),
        )

        try:
            with os.fdopen(
                fd,
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump(
                    clean,
                    handle,
                    indent=2,
                    sort_keys=True,
                )
                handle.write("\n")

            os.replace(
                tmp_name,
                CONFIG_PATH,
            )

        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    return clean


def ensure_config() -> dict:
    config = load_config()

    if not CONFIG_PATH.exists():
        save_config(config)

    return config
