"""Number platform for SOMA BLE blinds.

Reads and sets the device's timezone offset via the Shade Config service.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, MODEL


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the SOMA BLE timezone offset number entity."""
    device = hass.data[DOMAIN][entry.entry_id]["device"]
    entity = SomaBleTimeOffset(device, entry.entry_id)
    async_add_entities([entity], False)
    hass.async_create_task(entity._initial_read())


class SomaBleTimeOffset(NumberEntity):
    """SOMA blind timezone offset."""

    _attr_has_entity_name = True
    _attr_name = "Timezone offset"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False
    _attr_native_min_value = -12.0
    _attr_native_max_value = 14.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = UnitOfTime.HOURS

    def __init__(self, device: Any, entry_id: str) -> None:
        """Initialize the number entity."""
        self._device = device
        self._attr_unique_id = f"{entry_id}_time_offset"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.unique_id)},
            name=device.name,
            manufacturer=MANUFACTURER,
            model=MODEL,
            connections={("mac", device.mac)},
        )

    @property
    def native_value(self) -> float | None:
        """Return the cached timezone offset."""
        offset = self._device.local_time_offset_hours
        if offset is not None:
            return float(offset)
        return None

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
        """Called when device pushes a new value."""
        self.async_write_ha_state()

    async def _initial_read(self) -> None:
        """Background read of the timezone offset at startup."""
        offset = await self._device.read_local_time_offset()
        if offset is not None:
            self.async_write_ha_state()

    # --- Command ---

    async def async_set_native_value(self, value: float) -> None:
        """Set the timezone offset."""
        await self._device.set_local_time_offset(int(value))
