# Progre Face Pipeline Specification

**Version:** 0.1
**Status:** Architectural baseline

## Core Rule

Progre maintains exactly two installed face assets:

- **Idle** — waiting and ready.
- **Talk / Active** — listening, processing, and speaking.

There is no on-device face gallery or historical face collection.
Installing a new pair replaces the previous pair.

## Visual State Mapping

```text
BOOT -> IDLE
Talk pressed -> ACTIVE
Listening -> ACTIVE
Processing -> ACTIVE
Speaking -> ACTIVE
Conversation complete -> IDLE
```

Listening, processing, and speaking may remain separate internal
software states, but visually all three use the Active frame.

## Canonical Format

- 128 x 128 pixels
- black background
- white monochrome line art
- exactly one Idle image
- exactly one Talk image

## Face Package

Idle and Talk form one logical face package.
They should be replaced together rather than independently.
If installation fails, the previously valid pair should remain usable.

## Cockpit Face Converter

The Progre Cockpit will accept exactly two PNG/JPG source images:

1. Idle
2. Talk

The converter will validate or normalize dimensions and colors,
preview the hardware representation, build a device-ready pair,
and replace the currently installed pair.

Changing the face should eventually require neither an OS rebuild
nor retention of old face assets on the physical device.

## Phase 1K Acceptance

1. Canonical Idle frame renders correctly.
2. Canonical Active frame renders correctly.
3. Talk press changes Idle to Active.
4. Listening, processing, and speaking remain Active.
5. Completion returns to Idle.
6. Only two installed face assets exist.
