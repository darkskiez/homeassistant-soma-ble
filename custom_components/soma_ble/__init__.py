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

from bleak import BleakClient
from bleak.exc import BleakError

from homeassistant.components.bluetooth import (
    async_register_callback,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import (
    AVAILABILITY_TIMEOUT,
    CMD_DOWN,
    CMD_STOP,
    CMD_UP,
    CONFIG_ITEM_LOCAL_TIME_OFFSET,
    CONFIG_QUERY_PREFIX,
    CONNECT_TIMEOUT,
    DOMAIN,
    HARDWARE_REVISION_UUID,
    LOCAL_TIME_CHAR_UUID,
    MANUFACTURER_ID,
    MANUFACTURER_NAME_UUID,
    MOTOR_CONTROL_UUID,
    MOTOR_SOLAR_PANEL_VOLTAGE_UUID,
    MOTOR_TARGET_STATE_UUID,
    MOTOR_UNDER_VOLTAGE_UUID,
    RESPONSE_TIMEOUT,
    SHADE_CONFIG_CHAR_UUID,
    SOFTWARE_REVISION_UUID,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["cover", "sensor", "datetime", "number"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SOMA BLE from a config entry."""
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    mac = entry.data["mac"]
    name = entry.data.get("name")

    device = SomaBlindDevice(mac, name)

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
        self._solar_voltage: int | None = None
        self._under_voltage: bool | None = None
        self._manufacturer_name: str | None = None
        self._hardware_revision: str | None = None
        self._software_revision: str | None = None
        self._last_seen: float | None = None
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

        # SOMA: 0 = open, 100 = closed → HA: 0 = closed, 100 = open
        self._position = max(0, min(100, 100 - raw_pos))
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
            "Adv %s: pos=%s bat=%s%s",
            self._mac[-5:],
            self._position,
            self._battery,
            " (venetian)" if venetian else "",
        )

        self._notify_listeners()

    # --- BLE commands ---

    async def _ble_write(self, char_uuid: str, data: bytes) -> None:
        """Connect and write to a BLE characteristic."""
        async with self._lock:
            try:
                async with BleakClient(self._mac, timeout=CONNECT_TIMEOUT) as client:
                    await client.write_gatt_char(char_uuid, data, response=True)
            except (BleakError, TimeoutError, AttributeError) as err:
                _LOGGER.warning("BLE write error on %s: %s", self._mac, err)
                raise

    async def _ble_read(self, char_uuid: str) -> bytearray | None:
        """Connect and read a BLE characteristic."""
        async with self._lock:
            try:
                async with BleakClient(self._mac, timeout=CONNECT_TIMEOUT) as client:
                    return await client.read_gatt_char(char_uuid)
            except (BleakError, TimeoutError, AttributeError) as err:
                _LOGGER.warning("BLE read error on %s: %s", self._mac, err)
                raise

    async def open(self) -> None:
        """Open the blind fully."""
        await self._ble_write(MOTOR_CONTROL_UUID, CMD_UP)
        self._position = 100
        self._notify_listeners()

    async def close(self) -> None:
        """Close the blind fully."""
        await self._ble_write(MOTOR_CONTROL_UUID, CMD_DOWN)
        self._position = 0
        self._notify_listeners()

    async def stop(self) -> None:
        """Stop the blind."""
        await self._ble_write(MOTOR_CONTROL_UUID, CMD_STOP)

    async def set_position(self, position: int) -> None:
        """Move the blind to a position (HA: 0 = closed, 100 = open)."""
        position = max(0, min(100, position))
        # Invert for SOMA protocol (0 = open, 100 = closed)
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
                async with BleakClient(self._mac, timeout=CONNECT_TIMEOUT) as client:
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

    # --- Diagnostics (periodic polling) ---

    def start_polling(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Start a background task that periodically refreshes diagnostic values."""
        stop_event = asyncio.Event()

        async def _poll_loop() -> None:
            while not stop_event.is_set():
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=300)
                except asyncio.TimeoutError:
                    await self._refresh_diagnostics()

        task = hass.async_create_task(_poll_loop())

        def _stop() -> None:
            stop_event.set()
            task.cancel()

        entry.async_on_unload(_stop)

    async def _refresh_diagnostics(self) -> None:
        """Read solar voltage and under-voltage in a single BLE session."""
        async with self._lock:
            try:
                async with BleakClient(self._mac, timeout=CONNECT_TIMEOUT) as client:
                    try:
                        data = await client.read_gatt_char(MOTOR_SOLAR_PANEL_VOLTAGE_UUID)
                        if data and len(data) >= 2:
                            self._solar_voltage = struct.unpack("<H", data)[0]
                    except (BleakError, TimeoutError, AttributeError) as err:
                        _LOGGER.debug("Solar voltage not available on %s: %s", self._mac, err)
                    try:
                        data = await client.read_gatt_char(MOTOR_UNDER_VOLTAGE_UUID)
                        if data and len(data) >= 1:
                            self._under_voltage = bool(data[0])
                    except (BleakError, TimeoutError, AttributeError) as err:
                        _LOGGER.debug("Under-voltage not available on %s: %s", self._mac, err)
            except (BleakError, TimeoutError, AttributeError) as err:
                _LOGGER.debug("Diagnostic refresh failed on %s: %s", self._mac, err)
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
