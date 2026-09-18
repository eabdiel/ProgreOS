"""Safe Progre/AIPI recovery operations.

Backup operations are read-only. Destructive restore/install operations
must remain separately gated by verified recovery state.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "device"
BACKUPS = DATA / "backups"
LIFECYCLE = DATA / "lifecycle.json"

FLASH_SIZE = 0x1000000  # 16 MiB


def _esptool_command():
    """Return a portable esptool invocation."""
    candidates = [
        ROOT / ".progre-venv" / (
            "Scripts" if os.name == "nt" else "bin"
        ) / ("python.exe" if os.name == "nt" else "python"),
    ]

    for py in candidates:
        if py.is_file():
            try:
                subprocess.run(
                    [str(py), "-m", "esptool", "version"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                    check=True,
                )
                return [str(py), "-m", "esptool"]
            except Exception:
                pass

    if shutil.which("esptool"):
        return ["esptool"]

    if shutil.which("esptool.py"):
        return ["esptool.py"]

    raise RuntimeError(
        "ESPTool is not installed. Cockpit must install its recovery "
        "dependency before backup or firmware operations."
    )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)

    return h.hexdigest()


def _load_lifecycle():
    try:
        return json.loads(LIFECYCLE.read_text())
    except Exception:
        return {}


def _save_lifecycle(data):
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = LIFECYCLE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(LIFECYCLE)


def backup(serial_port: str):
    """Create and verify a complete 16 MiB flash backup."""
    if not serial_port:
        raise ValueError("A serial port is required.")

    BACKUPS.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final = BACKUPS / f"aipi-stock-{stamp}.bin"
    partial = final.with_suffix(".partial")

    if partial.exists():
        partial.unlink()

    cmd = _esptool_command() + [
        "--chip", "esp32s3",
        "--port", serial_port,
        "--before", "default-reset",
        "--after", "hard-reset",
        "read-flash",
        "0x0",
        hex(FLASH_SIZE),
        str(partial),
    ]

    try:
        subprocess.run(cmd, check=True)
    except Exception:
        partial.unlink(missing_ok=True)
        raise

    size = partial.stat().st_size

    if size != FLASH_SIZE:
        partial.unlink(missing_ok=True)
        raise RuntimeError(
            f"Backup verification failed: expected {FLASH_SIZE} bytes, "
            f"received {size}."
        )

    digest = _sha256(partial)
    partial.replace(final)

    lifecycle = _load_lifecycle()
    recovery = lifecycle.setdefault("recovery", {})

    recovery.update({
        "stock_backup": str(final.relative_to(ROOT)),
        "backup_verified": True,
        "backup_size": size,
        "backup_sha256": digest,
        "backup_created_utc": stamp,
        "serial_port": serial_port,
    })

    _save_lifecycle(lifecycle)

    return {
        "ok": True,
        "verified": True,
        "file": str(final),
        "size": size,
        "sha256": digest,
        "created_utc": stamp,
    }


def verified_backup():
    """Revalidate the recorded recovery image before destructive use."""
    lifecycle = _load_lifecycle()
    recovery = lifecycle.get("recovery", {})

    stored = recovery.get("stock_backup")

    if not stored:
        return {"ok": False, "verified": False, "reason": "no_backup"}

    path = ROOT / stored

    if not path.is_file():
        return {"ok": False, "verified": False, "reason": "backup_missing"}

    size = path.stat().st_size
    digest = _sha256(path)

    expected_size = recovery.get("backup_size")
    expected_hash = recovery.get("backup_sha256")

    valid = (
        recovery.get("backup_verified") is True
        and size == FLASH_SIZE
        and size == expected_size
        and digest == expected_hash
    )

    return {
        "ok": valid,
        "verified": valid,
        "file": str(path),
        "size": size,
        "sha256": digest,
        "reason": None if valid else "verification_failed",
    }
