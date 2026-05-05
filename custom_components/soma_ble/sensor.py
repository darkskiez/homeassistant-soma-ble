"""Sensor platform for SOMA BLE blinds."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
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
    """Set up the SOMA BLE sensor."""
    device = hass.data[DOMAIN][entry.entry_id]["device"]
    async_add_entities([SomaBleBatterySensor(device, entry.entry_id)], False)


class SomaBleBatterySensor(SensorEntity):
    """SOMA blind battery sensor, driven by BLE advertisements."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False

    def __init__(self, device: Any, entry_id: str) -> None:
        """Initialize the sensor."""
        self._device = device
        self._attr_unique_id = f"{entry_id}_battery"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.unique_id)},
            name=device.name,
            manufacturer=MANUFACTURER,
            model=MODEL,
            connections={("mac", device.mac)},
        )

    @property
    def native_value(self) -> int | None:
        return self._device.battery

    @property
    def available(self) -> bool:
        return self._device.online

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
        """Called by the device when a new advertisement is parsed."""
        self.async_write_ha_state()
