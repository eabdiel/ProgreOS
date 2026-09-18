# Progre Portable Setup

## First launch

With Python 3 installed, run:

    python main.py

The launcher creates `.progre-venv`, installs only the small Cockpit Python
requirements, and starts the local Cockpit at `http://127.0.0.1:8766`.

Large runtimes, models, and voices are deliberately not installed silently.
Cockpit reports each dependency independently and exposes an Install action.
The local AI model installer is active when Ollama is present. Platform-safe
installers for the remaining large components are represented by the same API
contract and can be added without changing Progre firmware.

## Device detection

Use **Detect AIPI** with the device connected by USB. Cockpit identifies
Espressif USB hardware, probes for a Progre console signature when the serial
port is available, and distinguishes Progre, stock/unknown, and busy/recovery
states conservatively.

A stock/unknown device must not be destructively converted until Cockpit has
created and verified a full recovery backup. The destructive backup/flash
backend is intentionally not enabled in this portability checkpoint.

## Runtime ownership

Portable assets belong under `runtime/` and must not depend on Rend or a
specific user's home directory.

## USB commissioning (Phase 1L)

After flashing the Phase 1L firmware once, Wi-Fi and Voice Bridge settings are runtime NVS configuration. In Cockpit: Detect AIPI -> Scan Wi-Fi -> choose SSID -> enter password -> Connect Progre. The password is sent over the local USB serial connection and is not persisted by Cockpit. Bridge host/port are stored on Progre so moving to another computer does not require rebuilding firmware.
