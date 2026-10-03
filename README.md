# Progre OS

Experimental ESP32-S3 / AIPI Lite companion firmware with display, audio, Wi-Fi, and an external AI voice bridge architecture.

A project of **[ProgreTech LLC](https://progretech.com)**, owned and maintained by **Ed Rodriguez**. Third-party components and contributions retain their respective ownership and notices.

[Project website](https://progretech.com) · [Report an issue](https://github.com/eabdiel/ProgreOS/issues) · [Contribute](CONTRIBUTING.md)

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

## Collaboration

Device compatibility notes, setup documentation, and reproducible connection failures are useful ways to help. Read [CONTRIBUTING.md](CONTRIBUTING.md) for issue reports, proposed changes, and attribution requirements.

## License and reuse

No complete root license was found in this repository. Public availability alone does not grant a general right to reuse or redistribute the code. The maintainer needs to clarify the intended license before code contributions or redistribution.

Factory firmware images and hardware-vendor materials are separate from original project code. Preserve the existing prohibition on redistributing factory firmware images.

## More from ProgreTech

Explore [ProgreTech Mesh](https://mesh.progretech.com) for monitoring and interacting with independently running AI agents (sign-in required).

Discover the wider portfolio at [progretech.com](https://progretech.com). These links identify related products; they do not imply a bundled integration or shared license.
