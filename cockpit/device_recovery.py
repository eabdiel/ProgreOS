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
        "--before", "default_reset",
        "--after", "hard_reset",
        "read_flash",
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
        "source_state": source_state,
        "backup_kind": (
            "original_stock"
            if source_state == "stock_or_unknown"
            else "progre_snapshot"
            if source_state == "progre_detected"
            else "recovery_snapshot"
        ),
    })

    _save_lifecycle(lifecycle)

    return {
        "ok": True,
        "verified": True,
        "source_state": rec.get("source_state", "legacy"),
        "backup_kind": rec.get("backup_kind", "legacy"),
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
        "source_state": recovery.get("source_state", "legacy"),
        "backup_kind": recovery.get("backup_kind", "legacy"),
        "reason": None if valid else "verification_failed",
    }


# ---------------------------------------------------------------------------
# Guarded destructive operations
# ---------------------------------------------------------------------------

PROGRE_APP_OFFSET = 0x10000
PROGRE_APP_MAX_SIZE = 0x100000


def _require_verified_backup():
    """Freshly verify recovery media immediately before destructive work."""
    result = verified_backup()

    if not result.get("verified"):
        raise RuntimeError(
            "Destructive operation blocked: a verified recovery backup "
            "is required."
        )

    return result


def _require_original_stock_backup():
    """Require a freshly verified original-stock image for first conversion."""
    result = _require_verified_backup()

    if result.get("backup_kind") != "original_stock":
        raise RuntimeError(
            "First-time Progre installation is blocked: the verified "
            "backup is not classified as an original stock backup."
        )

    return result


def _current_detected_state():
    """Return the most recent authoritative Cockpit detection state."""
    lifecycle = _load_lifecycle()
    return lifecycle.get("detection", {}).get("state", "unknown")


def _require_install_backup():
    """Choose the recovery requirement from the attached device state."""
    state = _current_detected_state()

    if state == "stock_or_unknown":
        recovery = _require_original_stock_backup()
        mode = "first_install"

    elif state == "progre_detected":
        recovery = _require_verified_backup()

        if recovery.get("backup_kind") not in (
            "progre_snapshot",
            "original_stock",
        ):
            raise RuntimeError(
                "Progre reinstall blocked: the verified backup has "
                "unknown or legacy provenance."
            )

        mode = "reinstall_or_update"

    else:
        raise RuntimeError(
            "Progre installation blocked: Detect AIPI must classify "
            "the attached device as stock_or_unknown or progre_detected."
        )

    return state, mode, recovery


def _progre_firmware():
    """Locate and validate the locally built Progre application image."""
    candidates = [
        ROOT / "firmware" / "build" / "progre_os.bin",
        ROOT / "build" / "progre_os.bin",
    ]

    image = next((x for x in candidates if x.is_file()), None)

    if image is None:
        raise RuntimeError(
            "Progre OS firmware image is unavailable. Build or install "
            "a validated firmware release first."
        )

    size = image.stat().st_size

    if size <= 0 or size > PROGRE_APP_MAX_SIZE:
        raise RuntimeError(
            f"Progre firmware size {size} is outside the accepted "
            f"1 MiB application partition."
        )

    return {
        "file": image,
        "size": size,
        "sha256": _sha256(image),
    }


def install_preflight():
    """Validate everything required to install Progre without writing."""
    detected_state, install_mode, recovery = _require_install_backup()
    firmware = _progre_firmware()

    return {
        "ok": True,
        "ready": True,
        "detected_state": detected_state,
        "install_mode": install_mode,
        "recovery": recovery,
        "firmware": {
            "file": str(firmware["file"]),
            "size": firmware["size"],
            "sha256": firmware["sha256"],
            "offset": PROGRE_APP_OFFSET,
        },
    }


def restore_preflight():
    """Validate everything required to restore the recorded full backup."""
    recovery = _require_verified_backup()

    if recovery.get("size") != FLASH_SIZE:
        raise RuntimeError(
            "Restore blocked: recovery image is not exactly 16 MiB."
        )

    return {
        "ok": True,
        "ready": True,
        "backup_kind": recovery.get("backup_kind", "unknown"),
        "source_state": recovery.get("source_state", "unknown"),
        "recovery": recovery,
    }


def install_progre(serial_port: str):
    """Install the validated Progre application image after fresh backup gate."""
    if not serial_port:
        raise ValueError("A serial port is required.")

    # Repeat the authoritative state/provenance gate immediately
    # before constructing the destructive command.
    _require_install_backup()
    firmware = _progre_firmware()

    cmd = _esptool_command() + [
        "--chip", "esp32s3",
        "--port", serial_port,
        "--before", "default_reset",
        "--after", "hard_reset",
        "write_flash",
        hex(PROGRE_APP_OFFSET),
        str(firmware["file"]),
    ]

    subprocess.run(cmd, check=True)

    lifecycle = _load_lifecycle()
    provisioning = lifecycle.setdefault("provisioning", {})

    provisioning.update({
        "progre_installed": True,
        "last_provisioned": datetime.now(timezone.utc).isoformat(),
        "firmware_file": str(firmware["file"].relative_to(ROOT)),
        "firmware_size": firmware["size"],
        "firmware_sha256": firmware["sha256"],
        "flash_offset": PROGRE_APP_OFFSET,
    })

    _save_lifecycle(lifecycle)

    return {
        "ok": True,
        "installed": True,
        "size": firmware["size"],
        "sha256": firmware["sha256"],
        "offset": PROGRE_APP_OFFSET,
    }


def restore_backup(serial_port: str):
    """Restore the complete verified recovery image after fresh verification."""
    if not serial_port:
        raise ValueError("A serial port is required.")

    # Fresh hash/size verification is intentionally performed here,
    # immediately before the destructive operation.
    recovery = _require_verified_backup()

    if recovery.get("size") != FLASH_SIZE:
        raise RuntimeError(
            "Restore blocked: recovery image is not exactly 16 MiB."
        )

    image = Path(recovery["file"])

    cmd = _esptool_command() + [
        "--chip", "esp32s3",
        "--port", serial_port,
        "--before", "default_reset",
        "--after", "hard_reset",
        "write_flash",
        "0x0",
        str(image),
    ]

    subprocess.run(cmd, check=True)

    lifecycle = _load_lifecycle()
    provisioning = lifecycle.setdefault("provisioning", {})

    provisioning.update({
        "progre_installed": False,
        "last_restored": datetime.now(timezone.utc).isoformat(),
        "restored_backup": str(image.relative_to(ROOT)),
        "restored_sha256": recovery["sha256"],
    })

    _save_lifecycle(lifecycle)

    return {
        "ok": True,
        "restored": True,
        "size": recovery["size"],
        "sha256": recovery["sha256"],
    }
