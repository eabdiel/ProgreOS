# Progre OS

Progre OS is the device-side firmware for the ProgreTech physical AI
companion.

Target hardware:

- AIPI Lite
- ESP32-S3 revision 0.2
- 8 MB PSRAM
- 16 MB SPI flash
- ST7735 LCD
- ES8311 audio codec

## Architecture

Progre OS is intentionally a thin physical endpoint.

The ESP32-S3 owns:

- display and expressions
- buttons and local interaction
- microphone and speaker hardware
- Wi-Fi connectivity
- device state
- recovery and OTA
- communication with the Progre Bridge

Higher-level intelligence remains external to the device.

The Progre Bridge owns:

- speech-to-text
- text-to-speech
- model routing
- durable memory
- Japanese-learning services
- Autonomous OS integration
- ProgreTech Mesh integration

## Recovery

The original 16 MiB factory flash image was independently captured twice
and verified byte-for-byte identical before development began.

Factory recovery SHA-256:

cffb5c062b12b8e30490473b07bcdc97fc4ee46f6408eb2d28888c4747f17c02

Original eFuse configuration was also captured before firmware modification.

Do not modify or redistribute factory firmware images.

## Development Principle

Bring hardware online incrementally.

First Light -> Controls -> Audio -> Network -> Bridge -> Companion

No irreversible eFuse operations are permitted by this project.
