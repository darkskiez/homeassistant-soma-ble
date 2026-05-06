"""Number platform for SOMA BLE blinds.

Config entities for device settings: timezone offset and motor speed.
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
    """Set up the SOMA BLE number entities."""
    device = hass.data[DOMAIN][entry.entry_id]["device"]
    entities: list[NumberEntity] = [
        SomaBleTimeOffset(device, entry.entry_id),
        SomaBleMotorSpeed(device, entry.entry_id),
    ]
    async_add_entities(entities, False)
    for ent in entities:
        hass.async_create_task(ent._initial_read())


def _device_info(device: Any) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, device.unique_id)},
        name=device.name,
        manufacturer=MANUFACTURER,
        model=MODEL,
        connections={("mac", device.mac)},
    )


class _SomaBleConfigNumber(NumberEntity):
    """Base for config number entities that read via BLE at startup."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, device: Any, entry_id: str, suffix: str) -> None:
        self._device = device
        self._attr_unique_id = f"{entry_id}_{suffix}"
        self._attr_device_info = _device_info(device)

    @property
    def available(self) -> bool:
        return self._device.online

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._device.add_listener(self._state_update)

    async def async_will_remove_from_hass(self) -> None:
        self._device.remove_listener(self._state_update)
        await super().async_will_remove_from_hass()

    @callback
    def _state_update(self) -> None:
        self.async_write_ha_state()

    async def _initial_read(self) -> None:
        return


class SomaBleTimeOffset(_SomaBleConfigNumber):
    """SOMA blind timezone offset."""

    _attr_name = "Timezone offset"
    _attr_native_min_value = -12.0
    _attr_native_max_value = 14.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = UnitOfTime.HOURS

    def __init__(self, device: Any, entry_id: str) -> None:
        super().__init__(device, entry_id, "time_offset")

    @property
    def native_value(self) -> float | None:
        offset = self._device.local_time_offset_hours
        if offset is not None:
            return float(offset)
        return None

    async def _initial_read(self) -> None:
        offset = await self._device.read_local_time_offset()
        if offset is not None:
            self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        await self._device.set_local_time_offset(int(value))


class SomaBleMotorSpeed(_SomaBleConfigNumber):
    """SOMA blind motor speed."""

    _attr_name = "Motor speed"
    _attr_native_min_value = 1.0
    _attr_native_max_value = 255.0
    _attr_native_step = 1.0

    def __init__(self, device: Any, entry_id: str) -> None:
        super().__init__(device, entry_id, "motor_speed")

    @property
    def native_value(self) -> float | None:
        speed = self._device.motor_speed
        if speed is not None:
            return float(speed)
        return None

    async def _initial_read(self) -> None:
        speed = await self._device.read_motor_speed()
        if speed is not None:
            self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        await self._device.set_motor_speed(int(value))
