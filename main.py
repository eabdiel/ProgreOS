"""Portable Progre launcher.

Run:
    python main.py

Bootstraps Progre's private Python environment, starts the Voice Bridge and
Cockpit as managed child processes, verifies both services, and shuts down
only the processes it owns.
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".progre-venv"
REQ = ROOT / "bridge" / "requirements.txt"

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 8765
COCKPIT_HOST = "127.0.0.1"
COCKPIT_PORT = 8766


def vpython() -> Path:
    return VENV / (
        "Scripts/python.exe"
        if os.name == "nt"
        else "bin/python"
    )


def port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection(
            (host, port),
            timeout=0.4,
        ):
            return True
    except OSError:
        return False


def http_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(
            url,
            timeout=1.0,
        ) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


def wait_ready(
    name: str,
    process: subprocess.Popen,
    url: str,
    timeout: float = 15.0,
) -> None:
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"{name} stopped during startup "
                f"(exit {process.returncode})."
            )

        if http_ready(url):
            print(f"[Progre] {name}: READY", flush=True)
            return

        time.sleep(0.25)

    raise RuntimeError(
        f"{name} did not become ready within "
        f"{timeout:.0f} seconds."
    )


def bootstrap() -> str:
    if not vpython().exists():
        print(
            "[Progre] Creating private environment...",
            flush=True,
        )
        venv.EnvBuilder(with_pip=True).create(VENV)

    py = str(vpython())
    marker = VENV / ".requirements-ready"

    if not marker.exists():
        print(
            "[Progre] Installing runtime dependencies...",
            flush=True,
        )
        subprocess.check_call(
            [
                py,
                "-m",
                "pip",
                "install",
                "-r",
                str(REQ),
            ]
        )
        marker.write_text("ready\n")

    return py


def stop_child(
    name: str,
    process: subprocess.Popen | None,
) -> None:
    if process is None or process.poll() is not None:
        return

    print(f"[Progre] Stopping {name}...", flush=True)

    process.terminate()

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        print(
            f"[Progre] {name} did not stop; "
            "forcing shutdown.",
            flush=True,
        )
        process.kill()
        process.wait(timeout=3)


def main() -> int:
    py = bootstrap()

    # Never kill arbitrary port owners.
    occupied = []

    if port_open(BRIDGE_HOST, BRIDGE_PORT):
        occupied.append(f"Voice Bridge :{BRIDGE_PORT}")

    if port_open(COCKPIT_HOST, COCKPIT_PORT):
        occupied.append(f"Cockpit :{COCKPIT_PORT}")

    if occupied:
        print()
        print("[Progre] Startup blocked.")
        print(
            "[Progre] These required ports are already in use:"
        )

        for item in occupied:
            print(f"  - {item}")

        print()
        print(
            "[Progre] Close the existing application and "
            "run python main.py again."
        )
        print(
            "[Progre] No existing process was terminated."
        )
        return 2

    bridge = None
    cockpit = None

    try:
        print("=" * 60)
        print(" PROGRE")
        print("=" * 60)

        print(
            f"[Progre] Starting Voice Bridge "
            f"on :{BRIDGE_PORT}...",
            flush=True,
        )

        bridge = subprocess.Popen(
            [py, str(ROOT / "bridge" / "main.py")],
            cwd=str(ROOT / "bridge"),
        )

        wait_ready(
            "Voice Bridge",
            bridge,
            f"http://{BRIDGE_HOST}:{BRIDGE_PORT}/health",
        )

        print(
            f"[Progre] Starting Cockpit "
            f"on :{COCKPIT_PORT}...",
            flush=True,
        )

        cockpit = subprocess.Popen(
            [py, str(ROOT / "cockpit" / "main.py")],
            cwd=str(ROOT / "cockpit"),
        )

        wait_ready(
            "Cockpit",
            cockpit,
            f"http://{COCKPIT_HOST}:{COCKPIT_PORT}/api/status",
        )

        print()
        print("=" * 60)
        print(" PROGRE READY")
        print("=" * 60)
        print(
            f" Voice Bridge: "
            f"http://{BRIDGE_HOST}:{BRIDGE_PORT}"
        )
        print(
            f" Cockpit:      "
            f"http://{COCKPIT_HOST}:{COCKPIT_PORT}"
        )
        print()
        print(" Press Ctrl+C to stop Progre.")
        print("=" * 60)

        while True:
            if bridge.poll() is not None:
                raise RuntimeError(
                    "Voice Bridge stopped unexpectedly "
                    f"(exit {bridge.returncode})."
                )

            if cockpit.poll() is not None:
                raise RuntimeError(
                    "Cockpit stopped unexpectedly "
                    f"(exit {cockpit.returncode})."
                )

            time.sleep(0.5)

    except KeyboardInterrupt:
        print()
        print("[Progre] Shutdown requested.")

    except Exception as exc:
        print()
        print(f"[Progre] ERROR: {exc}")
        return 1

    finally:
        # Reverse startup order.
        stop_child("Cockpit", cockpit)
        stop_child("Voice Bridge", bridge)

    print("[Progre] Shutdown complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
