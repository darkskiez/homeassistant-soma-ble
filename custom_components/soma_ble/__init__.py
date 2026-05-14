"""SOMA BLE integration for Home Assistant.

State is tracked passively from BLE advertisement manufacturer data.
Commands (open/close/stop/set position) connect and write to characteristics.
"""

from __future__ import annotations

import asyncio
import logging
import struct
import time
from datetime import datetime as dt, timezone
from typing import Any, Callable

import voluptuous as vol

from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection

from homeassistant.components.bluetooth import (
    async_ble_device_from_address,
    async_register_callback,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import (
    AVAILABILITY_TIMEOUT,
    CALIBRATION_VENETIAN_OFF,
    CALIBRATION_VENETIAN_ON,
    CMD_DOWN,
    CMD_STOP,
    CMD_UP,
    CONFIG_ITEM_LOCAL_TIME_OFFSET,
    CONFIG_ITEM_MOTOR_SPEED,
    CONFIG_ITEM_SUNRISE_SUNSET,
    CONFIG_QUERY_PREFIX,
    CONNECT_TIMEOUT,
    DOMAIN,
    HARDWARE_REVISION_UUID,
    LOCAL_TIME_CHAR_UUID,
    MANUFACTURER_ID,
    MANUFACTURER_NAME_UUID,
    MOTOR_CALIBRATION_UUID,
    MOTOR_CONTROL_UUID,
    MOTOR_SOLAR_PANEL_VOLTAGE_UUID,
    MOTOR_TARGET_STATE_UUID,
    MOTOR_UNDER_VOLTAGE_UUID,
    RESPONSE_TIMEOUT,
    SHADE_CONFIG_CHAR_UUID,
    SHADE_CONFIG_DIAG_ITEMS,
    SOFTWARE_REVISION_UUID,
    SUNRISE_DIAG_ID,
    SUNSET_DIAG_ID,
    TILT_DOWN,
    TILT_DIRECTION_OPTIONS,
    TILT_UP,
    VENETIAN_MODE_OPTIONS,
    VENETIAN_OFF,
    VENETIAN_ON,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["cover", "sensor", "datetime", "number", "select", "button"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SOMA BLE from a config entry."""
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    mac = entry.data["mac"]
    name = entry.data.get("name")

    device = SomaBlindDevice(mac, name)
    device._hass = hass

    @callback
    def _advertisement_callback(
        service_info: BluetoothServiceInfoBleak,
        change: BluetoothChange,
    ) -> None:
        """Process a BLE advertisement from this blind."""
        if MANUFACTURER_ID not in service_info.manufacturer_data:
            return
        device._update_from_advertisement(
            service_info.manufacturer_data[MANUFACTURER_ID],
        )

    entry.async_on_unload(
        async_register_callback(
            hass,
            _advertisement_callback,
            {"address": mac},
            BluetoothScanningMode.ACTIVE,
        )
    )

    hass.data[DOMAIN][entry.entry_id] = {
        "device": device,
    }

    # Register domain-level service to force a shade config re-read.
    if not hass.services.has_service(DOMAIN, "refresh_shade_config"):
        refresh_schema = vol.Schema({vol.Required("entry_id"): str})

        async def _handle_refresh_shade_config(call: Any) -> None:
            dev = hass.data[DOMAIN][call.data["entry_id"]]["device"]
            await dev.force_refresh_shade_config()

        hass.services.async_register(
            DOMAIN,
            "refresh_shade_config",
            _handle_refresh_shade_config,
            schema=refresh_schema,
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Start periodic polling for diagnostic values (solar voltage, under voltage).
    device.start_polling(hass, entry)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


class SomaBlindDevice:
    """Tracks state of a SOMA blind from BLE advertisements and sends commands."""

    def __init__(self, mac: str, name: str | None = None) -> None:
        """Initialize the device."""
        self._mac = mac
        self._name = name or f"SOMA Blind {mac[-8:].replace(':', '').upper()}"
        self._position: int | None = None
        self._battery: int | None = None
        self._device_time: dt | None = None
        self._local_time_offset_hours: int | None = None
        self._motor_speed: int | None = None
        self._shade_config_data: dict[int, int | bytes] = {}
        self._solar_voltage: int | None = None
        self._under_voltage: bool | None = None
        self._has_solar_voltage = True
        self._has_under_voltage = True
        self._manufacturer_name: str | None = None
        self._hardware_revision: str | None = None
        self._software_revision: str | None = None
        self._last_seen: float | None = None
        self._venetian: bool = False
        self._tilt_direction: str = TILT_UP
        self._hass: HomeAssistant | None = None
        self._lock = asyncio.Lock()
        self._listeners: list[Callable[[], None]] = []

    # --- Public properties ---

    @property
    def mac(self) -> str:
        return self._mac

    @property
    def name(self) -> str:
        return self._name

    @property
    def position(self) -> int | None:
        """Cached position in HA format (0 = closed, 100 = open)."""
        return self._position

    @property
    def battery(self) -> int | None:
        """Cached battery level (0–100)."""
        return self._battery

    @property
    def online(self) -> bool:
        """True if an advertisement was received within AVAILABILITY_TIMEOUT."""
        if self._last_seen is None:
            return False
        return (time.monotonic() - self._last_seen) < AVAILABILITY_TIMEOUT

    @property
    def venetian(self) -> bool:
        """True if the blind is in venetian (tilt) mode."""
        return self._venetian

    async def set_venetian_mode(self, on: bool) -> None:
        """Enable or disable venetian mode on the device."""
        data = CALIBRATION_VENETIAN_ON if on else CALIBRATION_VENETIAN_OFF
        await self._ble_write(MOTOR_CALIBRATION_UUID, data)
        self._venetian = on
        if self._position is not None and on:
            await self.set_position(self._position)
        self._notify_listeners()

    @property
    def tilt_direction(self) -> str:
        """Current tilt direction: 'up' or 'down'."""
        return self._tilt_direction

    async def set_tilt_direction(self, direction: str) -> None:
        """Set the tilt direction for venetian blinds."""
        if direction not in TILT_DIRECTION_OPTIONS:
            return
        self._tilt_direction = direction
        if self._position is not None and self._venetian:
            await self.set_position(self._position)
        self._notify_listeners()

    @property
    def unique_id(self) -> str:
        return self._mac.replace(":", "").lower()

    @property
    def device_time(self) -> dt | None:
        """Cached device local time."""
        return self._device_time

    @property
    def local_time_offset_hours(self) -> int | None:
        """Cached timezone offset in hours (e.g. -5 for UTC-5)."""
        return self._local_time_offset_hours

    @property
    def motor_speed(self) -> int | None:
        """Cached motor speed setting (0–255)."""
        return self._motor_speed

    @property
    def shade_config_data(self) -> dict[int, int | bytes]:
        """Cached shade config values (item_id → parsed value)."""
        return self._shade_config_data

    @property
    def solar_voltage(self) -> int | None:
        """Cached solar panel voltage (raw uint16 from device)."""
        return self._solar_voltage

    @property
    def under_voltage(self) -> bool | None:
        """Cached under-voltage flag."""
        return self._under_voltage

    @property
    def manufacturer_name(self) -> str | None:
        return self._manufacturer_name

    @property
    def hardware_revision(self) -> str | None:
        return self._hardware_revision

    @property
    def software_revision(self) -> str | None:
        return self._software_revision

    # --- Listener management ---

    def add_listener(self, listener: Callable[[], None]) -> None:
        """Register a callback invoked on each state update."""
        self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[], None]) -> None:
        """Unregister a callback."""
        self._listeners.remove(listener)

    def _notify_listeners(self) -> None:
        """Call all registered listeners."""
        for listener in self._listeners:
            listener()

    # --- Advertisement parsing ---

    def _update_from_advertisement(self, mfr_data: bytes) -> None:
        """Parse SOMA manufacturer data and update cached state.

        Manufacturer data format (offsets relative to company ID):
          [0-1] company ID (0x0370 LE)
          [2]   advDataProtocol
          [3]   battery (bit 7 = venetian mode flag)
          [4]   currentPosition
          [5]   targetPosition
          [6+]  displayName (null-terminated)
        """
        # Defensive: skip company ID if the BLE stack includes it
        data = mfr_data
        if len(data) >= 2 and data[0] == 0x70 and data[1] == 0x03:
            data = data[2:]

        if len(data) < 4:
            return

        battery_raw = data[1]
        venetian = bool(battery_raw & 0x80)
        bat = battery_raw & 0x7F
        raw_pos = data[2]
        raw_target = data[3]

        if venetian:
            raw_pos = raw_pos * 2 - 100
            raw_target = raw_target * 2 - 100
            self._position = max(0, min(100, 100 - abs(raw_pos)))
        else:
            self._position = max(0, min(100, 100 - raw_pos))
        self._venetian = venetian
        self._battery = min(100, bat)
        self._last_seen = time.monotonic()

        # Parse display name (if available)
        if len(data) > 4:
            name_bytes = data[4:]
            null = name_bytes.find(b"\x00")
            if null > 0:
                try:
                    decoded = name_bytes[:null].decode("ascii").strip()
                    if decoded:
                        # Strip trailing digit (firmware quirk: [^0-9 ]0$)
                        self._name = decoded
                except UnicodeDecodeError:
                    pass

        _LOGGER.debug(
            "Adv %s: proto=%s raw=%s venetian=%s bat=%s "
            "raw_pos=%s raw_target=%s pos=%s name=%s",
            self._mac[-5:],
            data[0],
            data.hex(),
            venetian,
            bat,
            raw_pos,
            raw_target,
            self._position,
            self._name,
        )

        self._notify_listeners()

    # --- BLE commands ---

    async def _ble_write(self, char_uuid: str, data: bytes) -> None:
        """Connect and write to a BLE characteristic."""
        async with self._lock:
            try:
                ble_device = async_ble_device_from_address(
                    self._hass, self._mac, connectable=True
                )
                client = await establish_connection(
                    BleakClient, ble_device, self._mac, timeout=CONNECT_TIMEOUT
                )
                async with client:
                    await client.write_gatt_char(char_uuid, data, response=True)
            except (BleakError, TimeoutError, AttributeError) as err:
                _LOGGER.warning("BLE write error on %s: %s", self._mac, err)
                raise

    async def _ble_read(self, char_uuid: str) -> bytearray | None:
        """Connect and read a BLE characteristic."""
        async with self._lock:
            try:
                ble_device = async_ble_device_from_address(
                    self._hass, self._mac, connectable=True
                )
                client = await establish_connection(
                    BleakClient, ble_device, self._mac, timeout=CONNECT_TIMEOUT
                )
                async with client:
                    return await client.read_gatt_char(char_uuid)
            except (BleakError, TimeoutError, AttributeError) as err:
                _LOGGER.warning("BLE read error on %s: %s", self._mac, err)
                raise

    async def open(self) -> None:
        """Open the blind fully."""
        if self._venetian:
            await self.set_position(100)
            return
        await self._ble_write(MOTOR_CONTROL_UUID, CMD_UP)
        self._position = 100
        self._notify_listeners()

    async def close(self) -> None:
        """Close the blind fully."""
        if self._venetian:
            await self.set_position(0)
            return
        await self._ble_write(MOTOR_CONTROL_UUID, CMD_DOWN)
        self._position = 0
        self._notify_listeners()

    async def stop(self) -> None:
        """Stop the blind."""
        await self._ble_write(MOTOR_CONTROL_UUID, CMD_STOP)

    async def set_position(self, position: int) -> None:
        """Move the blind to a position (HA: 0 = closed, 100 = open)."""
        position = max(0, min(100, position))
        if self._venetian:
            raw_abs = 100 - position
            raw_pos = raw_abs if self._tilt_direction == TILT_UP else -raw_abs
            cmd_pos = (raw_pos + 100) // 2
        else:
            cmd_pos = 100 - position
        await self._ble_write(MOTOR_TARGET_STATE_UUID, bytes([cmd_pos]))
        self._position = position
        self._notify_listeners()

    # --- Time ---

    async def read_time(self) -> dt | None:
        """Read the device local time via BLE."""
        try:
            data = await self._ble_read(LOCAL_TIME_CHAR_UUID)
            if data and len(data) >= 4:
                epoch = struct.unpack("<I", data)[0]
                self._device_time = dt.fromtimestamp(epoch, tz=timezone.utc)
                self._notify_listeners()
                return self._device_time
        except (BleakError, TimeoutError, AttributeError) as err:
            _LOGGER.warning("Failed to read time from %s: %s", self._mac, err)
        return None

    async def set_time(self, target: dt) -> None:
        """Set the device local time via BLE (requires tz-aware or assumes local)."""
        if target.tzinfo is None:
            target = target.astimezone()
        epoch = int(target.timestamp())
        await self._ble_write(LOCAL_TIME_CHAR_UUID, struct.pack("<I", epoch))
        self._device_time = target
        self._notify_listeners()

    # --- Shade Config (LocalTimeOffset) ---

    async def _ble_notify_command(
        self, char_uuid: str, write_data: bytes, timeout: int = RESPONSE_TIMEOUT
    ) -> bytearray | None:
        """Write to a characteristic and wait for a notification response."""
        response_data: bytearray | None = None
        event = asyncio.Event()

        def _handler(_sender: int, data: bytearray) -> None:
            nonlocal response_data
            response_data = data
            event.set()

        async with self._lock:
            try:
                ble_device = async_ble_device_from_address(
                    self._hass, self._mac, connectable=True
                )
                client = await establish_connection(
                    BleakClient, ble_device, self._mac, timeout=CONNECT_TIMEOUT
                )
                async with client:
                    await client.start_notify(char_uuid, _handler)
                    await client.write_gatt_char(char_uuid, write_data, response=True)
                    try:
                        await asyncio.wait_for(event.wait(), timeout=timeout)
                    except asyncio.TimeoutError:
                        _LOGGER.warning(
                            "No notification response from %s on %s", self._mac, char_uuid
                        )
                    finally:
                        await client.stop_notify(char_uuid)
            except (BleakError, TimeoutError, AttributeError) as err:
                _LOGGER.warning("BLE notify error on %s: %s", self._mac, err)
                raise

        return response_data

    async def read_local_time_offset(self) -> int | None:
        """Read the local time offset from Shade Config.

        Config item 0x06 stores an int8 where minutes = int8 * -60.
        Returns the offset in hours (e.g. -5 for UTC-5).
        """
        query = bytes([CONFIG_QUERY_PREFIX, 0x01, CONFIG_ITEM_LOCAL_TIME_OFFSET])
        response = await self._ble_notify_command(SHADE_CONFIG_CHAR_UUID, query)
        if response is None or len(response) < 3:
            return None
        if response[0] != CONFIG_ITEM_LOCAL_TIME_OFFSET:
            return None
        int8_val = response[2]
        # Clamp to signed int8 range
        if int8_val > 127:
            int8_val -= 256
        self._local_time_offset_hours = -int8_val
        self._notify_listeners()
        return self._local_time_offset_hours

    async def set_local_time_offset(self, offset_hours: int) -> None:
        """Set the local time offset via Shade Config.

        Converts hours to the device int8 format where int8 = -offset_hours.
        """
        int8_val = (-offset_hours) & 0xFF
        data = bytes([CONFIG_ITEM_LOCAL_TIME_OFFSET, 0x01, int8_val])
        await self._ble_write(SHADE_CONFIG_CHAR_UUID, data)
        self._local_time_offset_hours = offset_hours
        self._notify_listeners()

    # --- Shade Config (Motor Speed) ---

    async def read_motor_speed(self) -> int | None:
        """Read the motor speed setting (config item 0x01, uint8)."""
        query = bytes([CONFIG_QUERY_PREFIX, 0x01, CONFIG_ITEM_MOTOR_SPEED])
        response = await self._ble_notify_command(SHADE_CONFIG_CHAR_UUID, query)
        if response is None or len(response) < 3:
            return None
        if response[0] != CONFIG_ITEM_MOTOR_SPEED:
            return None
        self._motor_speed = response[2]
        self._notify_listeners()
        return self._motor_speed

    async def set_motor_speed(self, speed: int) -> None:
        """Set the motor speed (0–255)."""
        data = bytes([CONFIG_ITEM_MOTOR_SPEED, 0x01, speed & 0xFF])
        await self._ble_write(SHADE_CONFIG_CHAR_UUID, data)
        self._motor_speed = speed
        self._notify_listeners()

    # --- Shade Config (batch diagnostic read) ---

    async def _query_single_config(
        self, client: BleakClient, query: bytes
    ) -> int | bytes | None:
        """Query a single config item via an already-connected client.

        Starts notify, writes the query, waits for one notification,
        then stops notify. Returns the parsed value.
        """
        response: bytearray | None = None
        event = asyncio.Event()

        def _handler(_sender: int, data: bytearray) -> None:
            nonlocal response
            response = data
            event.set()

        await client.start_notify(SHADE_CONFIG_CHAR_UUID, _handler)
        try:
            await client.write_gatt_char(SHADE_CONFIG_CHAR_UUID, query, response=True)
            await asyncio.wait_for(event.wait(), timeout=RESPONSE_TIMEOUT)
        except asyncio.TimeoutError:
            return None
        finally:
            await client.stop_notify(SHADE_CONFIG_CHAR_UUID)

        if response is None or len(response) < 4:
            return None

        # The device responds with a batch-style TLV envelope:
        #   [0xFF][total_len][item_id][item_len][data...]
        # Skip the 0xFF command byte and total length.
        if response[0] == CONFIG_QUERY_PREFIX:
            item_id = response[2]
            length = response[3]
            raw = response[4 : 4 + length]
        else:
            item_id = response[0]
            length = response[1]
            raw = response[2 : 2 + length]
        _LOGGER.debug(
            "_query_single item=0x%02x len=%d raw_hex=%s",
            item_id, length, raw.hex(),
        )
        if length == 1:
            return raw[0]
        elif length == 2:
            return struct.unpack("<H", raw)[0]
        elif length == 4:
            return struct.unpack("<I", raw)[0]
        else:
            return bytes(raw)

    # --- Diagnostics (periodic polling) ---

    def start_polling(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Start a background task that periodically refreshes diagnostic values."""
        stop_event = asyncio.Event()

        async def _poll_loop() -> None:
            # Run first refresh immediately, then loop every 300 s.
            await self._refresh_diagnostics()
            while not stop_event.is_set():
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=300)
                except asyncio.TimeoutError:
                    await self._refresh_diagnostics()

        task = hass.async_create_background_task(
            _poll_loop(), name=f"soma_ble_poll_{self._mac}"
        )

        def _stop() -> None:
            stop_event.set()
            task.cancel()

        entry.async_on_unload(_stop)

    async def _refresh_diagnostics(self) -> None:
        """Read voltage diagnostics and shade configs in a single BLE session."""
        async with self._lock:
            try:
                ble_device = async_ble_device_from_address(
                    self._hass, self._mac, connectable=True
                )
                client = await establish_connection(
                    BleakClient, ble_device, self._mac, timeout=CONNECT_TIMEOUT
                )
                async with client:
                    self._last_seen = time.monotonic()
                    if self._has_solar_voltage:
                        try:
                            data = await client.read_gatt_char(MOTOR_SOLAR_PANEL_VOLTAGE_UUID)
                            if data and len(data) >= 2:
                                self._solar_voltage = struct.unpack("<H", data)[0]
                        except (BleakError, TimeoutError, AttributeError) as err:
                            _LOGGER.debug("Solar voltage not available on %s: %s", self._mac, err)
                            self._has_solar_voltage = False
                    if self._has_under_voltage:
                        try:
                            data = await client.read_gatt_char(MOTOR_UNDER_VOLTAGE_UUID)
                            if data and len(data) >= 1:
                                self._under_voltage = bool(data[0])
                        except (BleakError, TimeoutError, AttributeError) as err:
                            _LOGGER.debug("Under-voltage not available on %s: %s", self._mac, err)
                            self._has_under_voltage = False
                    # One-shot: read shade configs once we can reach the device.
                    if not self._shade_config_data:
                        await self._read_shade_configs_via_client(client)
            except (BleakError, TimeoutError, AttributeError) as err:
                _LOGGER.debug("Diagnostic refresh failed on %s: %s", self._mac, err)
                return
        self._notify_listeners()

    async def _read_shade_configs_via_client(self, client: BleakClient) -> None:
        """Read all shade config items sequentially via an active client."""
        item_ids = sorted(SHADE_CONFIG_DIAG_ITEMS)
        data: dict[int, int | bytes] = {}
        for item_id in item_ids:
            # Skip virtual diagnostic items (derived from multi-value responses)
            if item_id >= 0x70:
                continue
            try:
                query = bytes([CONFIG_QUERY_PREFIX, 0x01, item_id])
                val = await self._query_single_config(client, query)
                if item_id in (CONFIG_ITEM_MOTOR_SPEED, CONFIG_ITEM_LOCAL_TIME_OFFSET):
                    _LOGGER.debug(
                        "Config item 0x%02x val=%s type=%s",
                        item_id, val, type(val).__name__,
                    )
                if val is not None:
                    data[item_id] = val
            except (BleakError, TimeoutError, AttributeError) as err:
                _LOGGER.debug(
                    "Config item 0x%02x not available on %s: %s",
                    item_id, self._mac, err,
                )
        # Decode sunrise/sunset from 8-byte raw response (two uint32 LE epochs)
        raw_ss = data.get(CONFIG_ITEM_SUNRISE_SUNSET)
        _LOGGER.debug(
            "Shade config 0x17 raw %s len=%s hex=%s",
            "None" if raw_ss is None else type(raw_ss).__name__,
            len(raw_ss) if isinstance(raw_ss, (bytes, bytearray)) else "N/A",
            raw_ss.hex() if isinstance(raw_ss, (bytes, bytearray)) else "N/A",
        )
        if isinstance(raw_ss, (bytes, bytearray)) and len(raw_ss) >= 8:
            sunrise = struct.unpack("<I", raw_ss[0:4])[0]
            sunset = struct.unpack("<I", raw_ss[4:8])[0]
            _LOGGER.debug("Sunrise epoch=%s Sunset epoch=%s", sunrise, sunset)
            data[SUNRISE_DIAG_ID] = sunrise
            data[SUNSET_DIAG_ID] = sunset
        # Populate device-level cached values for Number entities
        if CONFIG_ITEM_MOTOR_SPEED in data and isinstance(data[CONFIG_ITEM_MOTOR_SPEED], int):
            self._motor_speed = data[CONFIG_ITEM_MOTOR_SPEED]
            _LOGGER.debug("Motor speed=%s", self._motor_speed)
        if CONFIG_ITEM_LOCAL_TIME_OFFSET in data and isinstance(data[CONFIG_ITEM_LOCAL_TIME_OFFSET], int):
            raw = data[CONFIG_ITEM_LOCAL_TIME_OFFSET]
            if raw > 127:
                raw -= 256
            self._local_time_offset_hours = -raw
            _LOGGER.debug("Local time offset=%s h", self._local_time_offset_hours)
        if data:
            _LOGGER.debug("Shade config read %d items", len(data))
            self._shade_config_data = data

    async def force_refresh_shade_config(self) -> None:
        """Force a BLE session to re-read all shade config items.

        Bypasses the one-shot guard so that newly added items (e.g. virtual
        sensors) are populated even when the initial read already succeeded.
        Used by the soma_ble.refresh_shade_config service.
        """
        async with self._lock:
            try:
                ble_device = async_ble_device_from_address(
                    self._hass, self._mac, connectable=True
                )
                client = await establish_connection(
                    BleakClient, ble_device, self._mac, timeout=CONNECT_TIMEOUT
                )
                async with client:
                    await self._read_shade_configs_via_client(client)
            except (BleakError, TimeoutError, AttributeError) as err:
                _LOGGER.warning(
                    "Force shade config refresh failed on %s: %s", self._mac, err
                )
                return
        self._notify_listeners()

    async def read_manufacturer_name(self) -> str | None:
        """Read the device manufacturer name."""
        try:
            data = await self._ble_read(MANUFACTURER_NAME_UUID)
            if data:
                name = data.decode("ascii", errors="replace").strip()
                self._manufacturer_name = name
                self._notify_listeners()
                return name
        except (BleakError, TimeoutError, AttributeError) as err:
            _LOGGER.warning("Failed to read manufacturer name from %s: %s", self._mac, err)
        return None

    async def read_hardware_revision(self) -> str | None:
        """Read the device hardware revision."""
        try:
            data = await self._ble_read(HARDWARE_REVISION_UUID)
            if data:
                rev = data.decode("ascii", errors="replace").strip()
                self._hardware_revision = rev
                self._notify_listeners()
                return rev
        except (BleakError, TimeoutError, AttributeError) as err:
            _LOGGER.warning("Failed to read hardware revision from %s: %s", self._mac, err)
        return None

    async def read_software_revision(self) -> str | None:
        """Read the device software revision."""
        try:
            data = await self._ble_read(SOFTWARE_REVISION_UUID)
            if data:
                rev = data.decode("ascii", errors="replace").strip()
                self._software_revision = rev
                self._notify_listeners()
                return rev
        except (BleakError, TimeoutError, AttributeError) as err:
            _LOGGER.warning("Failed to read software revision from %s: %s", self._mac, err)
        return None
