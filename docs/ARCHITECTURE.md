# Progre OS Architecture

## Device

The ESP32-S3 is a physical interface node, not the primary AI runtime.

### Hardware Layer

- ST7735 LCD
- ES8311 codec
- I2S microphone
- speaker
- buttons
- status hardware

### Device Services

- Wi-Fi
- connection management
- watchdog
- OTA
- recovery
- local state

### Progre UI

- idle
- listening
- thinking
- speaking
- disconnected
- error

### Progre Protocol

The device communicates with the external Progre Bridge over the local
network.

The protocol will be defined only after basic hardware bring-up succeeds.

## External Intelligence

The Progre Bridge may provide access to:

- STT
- TTS
- conversation management
- local models
- Japanese learning
- memory
- Autonomous OS
- ProgreTech Mesh

The device must remain useful and recoverable if those services are offline.
