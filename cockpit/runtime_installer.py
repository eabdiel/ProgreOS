from __future__ import annotations

import platform
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_jobs = {}
_lock = threading.Lock()


def platform_name():
    system = platform.system().lower()
    if system == "linux":
        return "linux"
    if system == "windows":
        return "windows"
    if system == "darwin":
        return "macos"
    return system or "unknown"


def _set(component, **values):
    with _lock:
        job = _jobs.setdefault(component, {})
        job.update(values)
        job["component"] = component
        job["updated"] = time.time()


def status(component=None):
    with _lock:
        if component:
            return dict(_jobs.get(component, {
                "component": component,
                "state": "idle",
            }))
        return {k: dict(v) for k, v in _jobs.items()}


def _verify(component):
    import sys

    bridge = ROOT / "bridge"
    if str(bridge) not in sys.path:
        sys.path.insert(0, str(bridge))

    from progre_runtime import readiness

    return bool(readiness().get(component, False))


def _require_tool(name):
    path = shutil.which(name)
    if not path:
        raise RuntimeError(
            f"{name} is required to install this component."
        )
    return path


def _download(url, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    partial = destination.with_suffix(destination.suffix + ".part")

    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            with partial.open("wb") as output:
                shutil.copyfileobj(response, output)

        partial.replace(destination)

    except Exception:
        partial.unlink(missing_ok=True)
        raise

    return destination


def _install_whisper():
    if platform_name() != "linux":
        raise RuntimeError(
            "Whisper automatic installation is currently implemented for Linux."
        )

    git = _require_tool("git")
    cmake = _require_tool("cmake")

    runtime = ROOT / "runtime"
    source = runtime / "sources" / "whisper.cpp"
    install_dir = runtime / "whisper"
    binary = install_dir / "whisper-cli"

    source.parent.mkdir(parents=True, exist_ok=True)
    install_dir.mkdir(parents=True, exist_ok=True)

    if not (source / ".git").exists():
        result = subprocess.run(
            [
                git,
                "clone",
                "--depth", "1",
                "https://github.com/ggml-org/whisper.cpp.git",
                str(source),
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )

        if result.returncode:
            raise RuntimeError(
                (result.stderr or result.stdout or "git clone failed")[-2000:]
            )

    build = source / "build"

    result = subprocess.run(
        [
            cmake,
            "-S", str(source),
            "-B", str(build),
            "-DCMAKE_BUILD_TYPE=Release",
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )

    if result.returncode:
        raise RuntimeError(
            (result.stderr or result.stdout or "cmake configure failed")[-2000:]
        )

    result = subprocess.run(
        [
            cmake,
            "--build", str(build),
            "--config", "Release",
            "-j2",
        ],
        capture_output=True,
        text=True,
        timeout=1800,
    )

    if result.returncode:
        raise RuntimeError(
            (result.stderr or result.stdout or "Whisper build failed")[-2000:]
        )

    built = build / "bin" / "whisper-cli"

    if not built.is_file():
        raise RuntimeError(
            "Whisper build completed but whisper-cli was not produced."
        )

    shutil.copy2(built, binary)
    binary.chmod(binary.stat().st_mode | 0o111)

    return "Whisper speech recognition installed."


def _install_whisper_model():
    model = ROOT / "runtime" / "models" / "ggml-base.en.bin"

    _download(
        "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin",
        model,
    )

    if not model.is_file() or model.stat().st_size < 10_000_000:
        model.unlink(missing_ok=True)
        raise RuntimeError(
            "Downloaded Whisper model did not pass size verification."
        )

    return "Whisper base.en speech model installed."


def _install_piper():
    if platform_name() != "linux":
        raise RuntimeError(
            "Piper automatic installation is currently implemented for Linux."
        )

    import venv

    piper_dir = ROOT / "runtime" / "piper"
    env_dir = piper_dir / "venv"
    wrapper = piper_dir / "piper"

    piper_dir.mkdir(parents=True, exist_ok=True)

    if not (env_dir / "bin" / "python").exists():
        venv.EnvBuilder(with_pip=True).create(env_dir)

    python = env_dir / "bin" / "python"

    result = subprocess.run(
        [
            str(python),
            "-m", "pip",
            "install",
            "--upgrade",
            "piper-tts",
        ],
        capture_output=True,
        text=True,
        timeout=1800,
    )

    if result.returncode:
        raise RuntimeError(
            (result.stderr or result.stdout or
             "Piper installation failed")[-3000:]
        )

    candidate = env_dir / "bin" / "piper"

    if not candidate.is_file():
        raise RuntimeError(
            "Piper package installed but its executable was not found."
        )

    wrapper.write_text(
        "#!/bin/sh\n"
        'HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"\n'
        'exec "$HERE/venv/bin/piper" "$@"\n'
    )
    wrapper.chmod(0o755)

    check = subprocess.run(
        [str(wrapper), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    if check.returncode not in (0, 1):
        raise RuntimeError(
            "Piper executable failed its startup verification."
        )

    return "Piper speech engine installed."


def _install_voice():
    voice_dir = ROOT / "runtime" / "voices"
    voice_dir.mkdir(parents=True, exist_ok=True)

    model = voice_dir / "en_US-arctic-medium.onnx"
    config = voice_dir / "en_US-arctic-medium.onnx.json"

    base = (
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
        "en/en_US/arctic/medium/"
    )

    _download(base + "en_US-arctic-medium.onnx", model)
    _download(base + "en_US-arctic-medium.onnx.json", config)

    if not model.is_file() or model.stat().st_size < 1_000_000:
        model.unlink(missing_ok=True)
        raise RuntimeError(
            "Downloaded Progre voice model failed verification."
        )

    if not config.is_file() or config.stat().st_size < 100:
        config.unlink(missing_ok=True)
        raise RuntimeError(
            "Downloaded Progre voice configuration failed verification."
        )

    piper = ROOT / "runtime" / "piper" / "piper"

    if not piper.is_file():
        raise RuntimeError(
            "Piper must be installed before installing Progre Voice."
        )

    test_wav = voice_dir / ".progre-voice-test.wav"

    try:
        result = subprocess.run(
            [
                str(piper),
                "--model", str(model),
                "--output_file", str(test_wav),
            ],
            input="Progre voice ready.",
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode:
            raise RuntimeError(
                (result.stderr or result.stdout or
                 "Voice synthesis verification failed")[-3000:]
            )

        if not test_wav.is_file() or test_wav.stat().st_size < 1000:
            raise RuntimeError(
                "Piper completed but did not produce valid test audio."
            )

    finally:
        test_wav.unlink(missing_ok=True)

    return "Progre voice installed and synthesis verified."


def _install_ai_model():
    import sys

    bridge = ROOT / "bridge"
    if str(bridge) not in sys.path:
        sys.path.insert(0, str(bridge))

    from progre_runtime import discover
    from progre_config import load_config

    ollama = discover().get("ollama")
    if not ollama:
        raise RuntimeError("Ollama is not installed.")

    model = load_config().get("model", "qwen3.5:2b")

    result = subprocess.run(
        [ollama, "pull", model],
        capture_output=True,
        text=True,
        timeout=3600,
    )

    if result.returncode:
        raise RuntimeError(
            (result.stderr or result.stdout or "ollama pull failed")[-2000:]
        )

    return f"Installed AI model {model}."


def _worker(component):
    try:
        _set(
            component,
            state="installing",
            progress=None,
            message="Installation started.",
            error=None,
        )

        if component == "ai_model":
            message = _install_ai_model()
        elif component == "whisper":
            message = _install_whisper()
        elif component == "whisper_model":
            message = _install_whisper_model()
        elif component == "piper":
            message = _install_piper()
        elif component == "voice":
            message = _install_voice()
        else:
            raise NotImplementedError(
                f"{component} installer is not implemented for "
                f"{platform_name()} yet."
            )

        if component == "ai_model":
            # ai_model readiness is checked by Cockpit against Ollama's
            # installed model list rather than progre_runtime.readiness().
            verified = True
        else:
            verified = _verify(component)

        if not verified:
            raise RuntimeError(
                "Installer completed but dependency verification failed."
            )

        _set(
            component,
            state="ready",
            progress=100,
            message=message,
            error=None,
        )

    except Exception as exc:
        _set(
            component,
            state="failed",
            progress=None,
            message="Installation failed.",
            error=str(exc),
        )


def start(component):
    with _lock:
        existing = _jobs.get(component)

        if existing and existing.get("state") == "installing":
            return {
                "ok": False,
                "error": "already_installing",
                "job": dict(existing),
            }

        _jobs[component] = {
            "component": component,
            "state": "queued",
            "progress": 0,
            "message": "Queued.",
            "error": None,
            "updated": time.time(),
        }

    thread = threading.Thread(
        target=_worker,
        args=(component,),
        daemon=True,
        name=f"progre-install-{component}",
    )
    thread.start()

    return {
        "ok": True,
        "component": component,
        "platform": platform_name(),
        "job": status(component),
    }
