# Progre Connectivity & Recovery Specification

**Version:** 0.1
**Status:** Architectural baseline

## Core Principle

USB is Progre's trusted local commissioning, recovery, and configuration channel.

The Progre Cockpit is the operator interface.

Wi-Fi credentials and other connection parameters are runtime device configuration and should not require rebuilding Progre OS.

## Diagnostic Chain

Cockpit troubleshooting should evaluate:

1. USB device connection
2. Progre OS responsiveness
3. Wi-Fi state
4. IP address / network status
5. Voice Bridge reachability
6. Whisper availability
7. Ollama availability
8. Piper availability

The operator should see the failing layer rather than a generic offline state.

## Cockpit Recovery Actions

Planned actions:

- Refresh device status
- Restart Voice Bridge
- Reconnect Wi-Fi
- Reboot Progre
- Run full diagnostic
- Configure Wi-Fi when Progre is connected by USB

## USB Control Protocol

Planned commissioning commands:

- status
- wifi_scan
- wifi_set
- wifi_reconnect
- reboot

The protocol should remain narrow and operational rather than becoming a second application API.

## Wi-Fi Provisioning

When Progre is connected by USB, Cockpit should:

1. detect the device;
2. request nearby Wi-Fi networks;
3. present an SSID dropdown;
4. allow password entry;
5. send credentials through the USB control path;
6. store credentials in ESP32 NVS;
7. request reconnection;
8. verify IP acquisition;
9. verify Voice Bridge handshake.

Credentials must not be written into tracked source files.

## Recovery UX

If Cockpit detects:

USB = connected
Wi-Fi = offline

it should surface a direct recovery message such as:

"Progre is connected locally but not online. Configure or reconnect Wi-Fi?"

## Factory / Conversion Reuse

The same USB workflow will support future AIPI Lite to Progre provisioning:

Flash Progre OS
-> configure Wi-Fi
-> validate Bridge
-> configure face pair
-> run hardware checks
-> create device manifest

## Phase 1L Plan

### 1L-1 Cockpit Diagnostics
USB detection, Bridge status, Ollama status, Whisper/Piper availability, and current network/device information.

### 1L-2 USB Control Protocol
Implement the narrow device command channel.

### 1L-3 Cockpit Wi-Fi Provisioning
SSID selection, password entry, NVS storage, reconnect, and verification.

### 1L-4 Recovery Workflow
One-click troubleshooting and appropriate repair actions.
