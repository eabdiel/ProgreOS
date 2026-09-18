# Progre Device Lifecycle Specification

## Operator Principle

The Progre Cockpit must hide firmware-development complexity from the
normal operator.

The operator should not need to know ESP-IDF commands, flash offsets,
serial-port commands, bootloader procedures, or firmware build details.

## Detect AIPI

Cockpit will provide a **Detect AIPI** action.

Detection should classify the attached hardware as one of:

- No compatible device detected
- AIPI Lite with stock/non-Progre firmware
- AIPI Lite running Progre OS
- AIPI Lite in bootloader/recovery mode
- AIPI-compatible hardware with unknown firmware
- Device detected but unresponsive

Detection should inspect hardware identity independently from firmware
identity whenever possible.

## Existing Progre Device

When Progre OS is detected, Cockpit should expose normal operational
actions including:

- device status
- Wi-Fi configuration
- reconnect
- Bridge configuration
- diagnostics
- reboot
- firmware update
- backup and recovery information

## Stock Device Conversion

A stock AIPI Lite must not be destructively converted without a verified
recovery backup.

Expected workflow:

Detect AIPI
-> identify hardware
-> identify firmware
-> create full flash backup
-> verify backup size
-> calculate backup hash
-> record device/recovery manifest
-> enable Install Progre OS
-> flash Progre OS
-> verify boot
-> provision Wi-Fi
-> configure Bridge
-> validate hardware
-> update device manifest

## Recovery Mode

If compatible hardware is detected in bootloader/recovery mode, Cockpit
should explain the state in operator-friendly language and expose only
appropriate recovery actions.

Possible actions include:

- Create Recovery Backup
- Restore Verified Backup
- Install Progre OS
- Retry Detection

Destructive actions require explicit confirmation.

## Backup

Stock backup records should include:

- hardware identity where available
- flash size
- backup file
- SHA-256
- creation timestamp
- verification result

A verified backup is a prerequisite for normal stock-to-Progre
conversion.

## Portability

Device lifecycle functionality belongs to Progre Cockpit and must not
depend on Rend or another ProgreTech agent installation.

The goal is:

Connect AIPI Lite by USB
-> launch Cockpit
-> Detect AIPI
-> recover or provision as appropriate
-> configure network
-> establish the local Progre runtime
-> ready

## Phase 1L Recovery Backup Acceptance

The Cockpit recovery-backup path has been physically validated on AIPI
Lite / ESP32-S3 hardware.

The accepted implementation:

- detects compatible hardware through Cockpit
- performs a read-only complete 16 MiB flash backup
- uses ESPTool 5.x command syntax
- writes first to a temporary `.partial` file
- requires an exact 16,777,216-byte result
- calculates and records SHA-256
- promotes the backup only after verification
- records verified recovery state in the local lifecycle manifest
- revalidates the file before it can satisfy a destructive-operation gate
- hard-resets the device after the completed read

The recovery module contains no flash-write, flash-erase, or eFuse-write
operation at this checkpoint.

Physical acceptance completed 2026-09-18.

Observed baseline full-flash read time was approximately 24 minutes.
Performance optimization is deferred; recovery correctness and safety take
priority over backup speed for this checkpoint.

A verified backup is the prerequisite for future guarded stock-to-Progre
installation and restore functionality.
