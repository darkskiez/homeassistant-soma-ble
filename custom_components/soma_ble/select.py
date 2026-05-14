"""Select platform for SOMA BLE blinds.

Direction toggle for venetian blinds.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DIRECTION_DOWN,
    DIRECTION_OPTIONS,
    DIRECTION_UP,
    DOMAIN,
    MANUFACTURER,
    MODEL,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the SOMA BLE select entities."""
    device = hass.data[DOMAIN][entry.entry_id]["device"]
    async_add_entities([SomaBleDirectionSelect(device, entry.entry_id)])


def _device_info(device: Any) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, device.unique_id)},
        name=device.name,
        manufacturer=MANUFACTURER,
        model=MODEL,
        connections={("mac", device.mac)},
    )


class SomaBleDirectionSelect(SelectEntity):
    """Select entity to set the tilt direction for venetian blinds."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Tilt direction"
    _attr_options = DIRECTION_OPTIONS

    def __init__(self, device: Any, entry_id: str) -> None:
        self._device = device
        self._attr_unique_id = f"{entry_id}_direction"
        self._attr_device_info = _device_info(device)

    @property
    def available(self) -> bool:
        return self._device.online

    @property
    def current_option(self) -> str | None:
        return self._device.direction

    async def async_select_option(self, option: str) -> None:
        self._device.set_direction(option)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._device.add_listener(self._state_update)

    async def async_will_remove_from_hass(self) -> None:
        self._device.remove_listener(self._state_update)
        await super().async_will_remove_from_hass()

    @callback
    def _state_update(self) -> None:
        self.async_write_ha_state()
