"""SOMA BLE integration for Home Assistant.

State is tracked passively from BLE advertisement manufacturer data.
Commands (open/close/stop/set position) connect and write to characteristics.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from bleak import BleakClient
from bleak.exc import BleakError

from homeassistant.components.bluetooth import (
    async_register_callback,
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
    CONNECT_TIMEOUT,
    DOMAIN,
    MANUFACTURER_ID,
    MOTOR_CONTROL_UUID,
    MOTOR_TARGET_STATE_UUID,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["cover", "sensor"]


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
