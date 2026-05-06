"""Datetime platform for SOMA BLE blinds.

Reads and sets the device's internal clock via the Time Service.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, MODEL

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the SOMA BLE datetime entity."""
    device = hass.data[DOMAIN][entry.entry_id]["device"]
    entity = SomaBleDateTime(device, entry.entry_id)
    async_add_entities([entity], False)
    # Read the current device time in the background.
    hass.async_create_task(entity._initial_read())


class SomaBleDateTime(DateTimeEntity):
    """SOMA blind device clock."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False

    def __init__(self, device: Any, entry_id: str) -> None:
        """Initialize the datetime entity."""
        self._device = device
        self._attr_unique_id = f"{entry_id}_datetime"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.unique_id)},
            name=device.name,
            manufacturer=MANUFACTURER,
            model=MODEL,
            connections={("mac", device.mac)},
        )

    @property
    def native_value(self) -> datetime | None:
        """Return the cached device time."""
        return self._device.device_time

    @property
    def available(self) -> bool:
        return self._device.online

    # --- Lifecycle ---

    async def async_added_to_hass(self) -> None:
        """Register for device state updates."""
        await super().async_added_to_hass()
        self._device.add_listener(self._state_update)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister from device state updates."""
        self._device.remove_listener(self._state_update)
        await super().async_will_remove_from_hass()

    @callback
    def _state_update(self) -> None:
        """Called when device pushes a new value (e.g. after set_time)."""
        self.async_write_ha_state()

    async def _initial_read(self) -> None:
        """Background read of the device clock at startup."""
        dt = await self._device.read_time()
        if dt is not None:
            self.async_write_ha_state()

    # --- Command ---

    async def async_set_value(self, value: datetime) -> None:
        """Set the device clock."""
        await self._device.set_time(value)
