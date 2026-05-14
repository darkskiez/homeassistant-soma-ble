"""Constants for the SOMA BLE integration."""

DOMAIN = "soma_ble"

MANUFACTURER_ID = 0x0370

# Service UUIDs (full 128-bit, base B87F-490C-92CB-11BA5EA5167C)
MOTOR_SERVICE_UUID = "00001861-B87F-490C-92CB-11BA5EA5167C"
SHADE_SERVICE_UUID = "00001890-B87F-490C-92CB-11BA5EA5167C"

# Time Service characteristics
TIME_SERVICE_UUID = "00001554-B87F-490C-92CB-11BA5EA5167C"
LOCAL_TIME_CHAR_UUID = "00001555-B87F-490C-92CB-11BA5EA5167C"

# Shade Service characteristics
SHADE_CONTROL_UUID = "00001891-B87F-490C-92CB-11BA5EA5167C"
SHADE_NAME_UUID = "00001892-B87F-490C-92CB-11BA5EA5167C"
SHADE_STATE_UUID = "00001894-B87F-490C-92CB-11BA5EA5167C"
SHADE_CONFIG_CHAR_UUID = "00001896-B87F-490C-92CB-11BA5EA5167C"

# Motor Service characteristics
MOTOR_CURRENT_STATE_UUID = "00001525-B87F-490C-92CB-11BA5EA5167C"
MOTOR_TARGET_STATE_UUID = "00001526-B87F-490C-92CB-11BA5EA5167C"
MOTOR_TRIGGER_REQUEST_UUID = "00001527-B87F-490C-92CB-11BA5EA5167C"
MOTOR_TRIGGER_RESPONSE_UUID = "00001528-B87F-490C-92CB-11BA5EA5167C"
MOTOR_CALIBRATION_UUID = "00001529-B87F-490C-92CB-11BA5EA5167C"
MOTOR_CONTROL_UUID = "00001530-B87F-490C-92CB-11BA5EA5167C"
MOTOR_NOTIFY_UUID = "00001531-B87F-490C-92CB-11BA5EA5167C"
MOTOR_BATTERY_LEVEL_UUID = "0000BA71-B87F-490C-92CB-11BA5EA5167C"
MOTOR_SOLAR_PANEL_VOLTAGE_UUID = "00001532-B87F-490C-92CB-11BA5EA5167C"
MOTOR_UNDER_VOLTAGE_UUID = "0000BA72-B87F-490C-92CB-11BA5EA5167C"

# Standard BLE Device Information characteristics
MANUFACTURER_NAME_UUID = "00002A29-0000-1000-8000-00805F9B34FB"
HARDWARE_REVISION_UUID = "00002A27-0000-1000-8000-00805F9B34FB"
SOFTWARE_REVISION_UUID = "00002A28-0000-1000-8000-00805F9B34FB"

# Motor Control command bytes (written to MOTOR_CONTROL_UUID)
CMD_STOP = bytes([0x00])
CMD_STOP_AT_NEXT_STEP = bytes([0x01])
CMD_STEP_UP = bytes([0x68])
CMD_UP = bytes([0x69])
CMD_STEP_DOWN = bytes([0x86])
CMD_DOWN = bytes([0x96])

# Shade Config TLV item IDs
CONFIG_ITEM_MOTOR_SPEED = 0x01
CONFIG_ITEM_LOCAL_TIME_OFFSET = 0x06
CONFIG_ITEM_BOOT_SEQ = 0x0C
CONFIG_ITEM_SUNRISE_SUNSET = 0x17

# Virtual diagnostic item IDs (not real shade config items; derived by the
# integration from raw multi-value responses, e.g. sunrise/sunset).
SUNRISE_DIAG_ID = 0x71
SUNSET_DIAG_ID = 0x72

# All shade config items mapped by ID → display info for diagnostic entities.
# Items with _device_class or _unit set are known-format values; others display as raw hex.
SHADE_CONFIG_DIAG_ITEMS: dict[int, tuple[str, str | None, str | None]] = {
    0x01: ("Motor speed", None, None),           # uint8, already a config Number
    0x02: ("Motor direction", None, None),
    0x03: ("Motor speed trigger", None, None),
    0x04: ("PID", None, None),
    0x05: ("Geo position", None, None),
    0x06: ("Local time offset", None, None),     # already a config Number
    0x07: ("Motor acceleration", None, None),
    0x08: ("Motor deceleration", None, None),
    0x09: ("Stall acceleration", None, None),
    0x0A: ("Encoder increment x2", None, None),
    0x0B: ("Encoder increment x4", None, None),
    0x0C: ("Boot sequence", None, None),         # uint32 LE
    0x0D: ("Reset reason", None, None),
    0x0E: ("Stop reason", None, None),
    0x0F: ("Power-off count", None, None),
    0x10: ("Slip length", None, None),
    0x11: ("Encoder max", None, None),
    0x12: ("Encoder current", None, None),
    0x13: ("Slip interval", None, None),
    0x14: ("Position moves total", None, None),
    0x15: ("Motor moves total", None, None),
    0x16: ("In calibration mode", None, None),
    0x17: ("Sunrise/sunset", None, None),        # two uint32 LE timestamps → decoded
    SUNRISE_DIAG_ID: ("Sunrise", "timestamp", None),
    SUNSET_DIAG_ID: ("Sunset", "timestamp", None),
    0x18: ("Motor current", None, None),
}

# Shade Config query prefix byte
CONFIG_QUERY_PREFIX = 0xFF

# Timeouts (seconds)
CONNECT_TIMEOUT = 10
RESPONSE_TIMEOUT = 5

# Availability: mark offline if no advertisement received in this window
AVAILABILITY_TIMEOUT = 900  # 15 minutes

# Tilt direction options for venetian blinds
DIRECTION_UP = "up"
DIRECTION_DOWN = "down"
DIRECTION_OPTIONS = [DIRECTION_UP, DIRECTION_DOWN]

# Manufacturer info
MANUFACTURER = "SOMA"
MODEL = "Smart Shade/Tilt"
