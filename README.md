# SOMA BLE Blinds

Home Assistant custom integration for SOMA Smart Shades 2.0 / SOMA Tilt using direct Bluetooth Low Energy (BLE) communication.

No cloud, no SOMA Connect hub required — just a Bluetooth adapter on your HA instance.

## Features

- **Passive state tracking** — position, battery, and device name are read from BLE advertisements. No polling, no unnecessary connections.
- **Full cover control** — open, close, stop, and set any position (0–100%).
- **Battery sensor** — battery percentage updated with each advertisement.
- **Auto-discovery** — SOMA blinds are detected automatically via Bluetooth.
- **Multiple blinds** — add as many as you like, each gets its own cover and battery sensor.

## Requirements

- Home Assistant 2024.x or later with the built-in Bluetooth integration configured.
- A compatible Bluetooth adapter (built-in, USB dongle, or ESPHome Bluetooth proxy).
- SOMA Smart Shades 2.0 (v2 BLE protocol, manufacturer ID `0x0370`).

## Installation

### Manual

Copy the `custom_components/soma_ble/` directory into your Home Assistant `config/custom_components/` directory.

### After installing

1. Restart Home Assistant.
2. Go to **Settings → Devices & Services → Add Integration**.
3. Search for **SOMA BLE Blinds**.
4. Discovered blinds will appear automatically. Select one, confirm, and you're done.
5. If your blind doesn't appear, choose **"Enter MAC address manually..."** and type its BLE address.

## Entities

Each blind creates:

| Entity | Domain | Description |
|---|---|---|
| Cover | `cover.soma_ble_*` | Open, close, stop, position control |
| Battery | `sensor.soma_ble_battery_*` | Battery percentage (0–100%) |
```
