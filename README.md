# SOMA BLE Blinds

Home Assistant custom integration for SOMA Smart Shades 2.0 / SOMA Tilt using direct Bluetooth Low Energy (BLE) communication.

No cloud, no SOMA Connect hub required — just a Bluetooth adapter on your HA instance.

## Features

- **Passive state tracking** — position, battery, and device name are read from BLE advertisements. No polling, no unnecessary connections.
- **Full cover control** — open, close, stop, and set any position (0–100%).
- **Fine positioning** — step up / step down buttons for precise adjustments.
- **Venetian / tilt support** — toggle venetian mode on/off and control tilt direction.
- **Device clock management** — read and set the device's internal clock.
- **Motor speed control** — configure motor speed (1–100%).
- **Timezone offset** — configure the device's timezone offset.
- **Battery sensor** — battery percentage updated with each advertisement.
- **Solar panel diagnostics** — solar panel voltage and under-voltage flag.
- **Device info** — manufacturer name, hardware revision, software revision.
- **Shade config diagnostics** — read internal device configuration items (motor direction, PID values, encoder data, sunrise/sunset timestamps, etc.).
- **Auto-discovery** — SOMA blinds are detected automatically via Bluetooth.
- **Multiple blinds** — add as many as you like, each gets its own set of entities.
- **Availability tracking** — blinds are marked offline if no BLE advertisement is received for 15 minutes.

## Requirements

- Home Assistant 2024.x or later with the built-in Bluetooth integration configured.
- A compatible Bluetooth adapter (built-in, USB dongle, or ESPHome Bluetooth proxy).
- SOMA Smart Shades 2.0 / SOMA Tilt (v2 BLE protocol, manufacturer ID `0x0370`).

## Installation

### HACS (custom repository)

1. Go to **HACS → Integrations → Custom repositories**
2. Add `https://github.com/darkskiez/homeassistant-soma-ble` with category **Integration**
3. Click **Install** on the SOMA BLE Blinds card

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

### Main control

| Entity | Domain | Description |
|---|---|---|
| Cover | `cover.soma_ble_*` | Open, close, stop, set position (0–100%) |
| Step up | `button.soma_ble_*_step_up` | Move blind up one increment |
| Step down | `button.soma_ble_*_step_down` | Move blind down one increment |

### Venetian / tilt (optional)

| Entity | Domain | Description |
|---|---|---|
| Venetian mode | `select.soma_ble_*_venetian_mode` | Enable or disable venetian (tilt) mode |
| Tilt direction | `select.soma_ble_*_tilt_direction` | Set tilt direction (up/down) — only available when venetian mode is on |

### Configuration

| Entity | Domain | Description |
|---|---|---|
| Device clock | `datetime.soma_ble_*_datetime` | Read and set the device's internal clock |
| Timezone offset | `number.soma_ble_*_time_offset` | Device timezone offset (-12 to +14 hours) |
| Motor speed | `number.soma_ble_*_motor_speed` | Motor speed setting (1–100%) |

### Sensors

| Entity | Domain | Description |
|---|---|---|
| Battery | `sensor.soma_ble_battery_*` | Battery percentage (0–100%) |
| Solar panel voltage | `sensor.soma_ble_*_solar_voltage` | Solar panel voltage (mV) |
| Under voltage | `sensor.soma_ble_*_under_voltage` | Under-voltage flag (ON/OFF) |

### Device info (diagnostic)

| Entity | Domain | Description |
|---|---|---|
| Manufacturer name | `sensor.soma_ble_*_manufacturer_name` | Device manufacturer |
| Hardware revision | `sensor.soma_ble_*_hardware_revision` | Hardware version |
| Software revision | `sensor.soma_ble_*_software_revision` | Software/firmware version |

### Shade config diagnostics

Each blind exposes diagnostic sensors for internal device configuration values, read via BLE. These include motor settings, encoder data, position counters, sunrise/sunset timestamps, and more.

| Entity | Description |
|---|---|
| Motor direction | Motor rotation direction |
| PID | PID control values |
| Geo position | Geographic position setting |
| Motor acceleration / deceleration | Acceleration and deceleration settings |
| Stall acceleration | Stall detection acceleration |
| Encoder increment x2 / x4 | Encoder increment values |
| Boot sequence | Device boot sequence number |
| Reset reason | Last reset reason |
| Stop reason | Last stop reason |
| Power-off count | Number of power-off events |
| Slip length / interval | Slip detection parameters |
| Encoder max / current | Encoder position values |
| Position moves total / Motor moves total | Move counters |
| In calibration mode | Whether the device is in calibration mode |
| Sunrise / Sunset | Decoded sunrise and sunset timestamps |
| Motor current | Motor current reading |

Use the **Refresh shade config** button or the `soma_ble.refresh_shade_config` service to trigger a re-read of these values.

### Services

| Service | Description |
|---|---|
| `soma_ble.refresh_shade_config` | Connect via BLE and re-read all shade config diagnostic items for a device |
```
