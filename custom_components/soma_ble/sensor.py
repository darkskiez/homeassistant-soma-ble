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
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, MODEL

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the SOMA BLE sensors."""
    device = hass.data[DOMAIN][entry.entry_id]["device"]
    sensors: list[SensorEntity] = [
        SomaBleBatterySensor(device, entry.entry_id),
        SomaBleSolarVoltageSensor(device, entry.entry_id),
        SomaBleUnderVoltageSensor(device, entry.entry_id),
        SomaBleManufacturerNameSensor(device, entry.entry_id),
        SomaBleHardwareRevisionSensor(device, entry.entry_id),
        SomaBleSoftwareRevisionSensor(device, entry.entry_id),
    ]
    async_add_entities(sensors, False)
    # One-time reads for static info (manufacturer, hw/sw rev).
    # Dynamic values (voltage, under-voltage) are handled by the polling loop.
    for s in sensors[3:]:
        hass.async_create_task(s._initial_read())


# --- Helpers ---


def _device_info(device: Any) -> DeviceInfo:
    """Build device info from a SomaBlindDevice."""
    return DeviceInfo(
        identifiers={(DOMAIN, device.unique_id)},
        name=device.name,
        manufacturer=MANUFACTURER,
        model=MODEL,
        connections={("mac", device.mac)},
    )


class _DiagnosticSensor(SensorEntity):
    """Base for diagnostic sensors that poll via BLE once at startup."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_name = None
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
        """Override in subclasses to read the sensor value at startup."""
        return


# --- Battery (advertisement-driven, no BLE read needed) ---


class SomaBleBatterySensor(SensorEntity):
    """SOMA blind battery sensor, driven by BLE advertisements."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False

    def __init__(self, device: Any, entry_id: str) -> None:
        """Initialize the sensor."""
        self._device = device
        self._attr_unique_id = f"{entry_id}_battery"
        self._attr_device_info = _device_info(device)

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


# --- Solar Panel Voltage ---


class SomaBleSolarVoltageSensor(_DiagnosticSensor):
    """Motor solar panel voltage."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_name = "Solar panel voltage"

    def __init__(self, device: Any, entry_id: str) -> None:
        super().__init__(device, entry_id, "solar_voltage")

    @property
    def native_value(self) -> int | None:
        return self._device.solar_voltage

    @property
    def native_unit_of_measurement(self) -> str | None:
        return "mV" if self._device.solar_voltage is not None else None

    async def _initial_read(self) -> None:
        return


# --- Under Voltage ---


class SomaBleUnderVoltageSensor(_DiagnosticSensor):
    """Motor under-voltage flag."""

    _attr_name = "Under voltage"

    def __init__(self, device: Any, entry_id: str) -> None:
        super().__init__(device, entry_id, "under_voltage")

    @property
    def native_value(self) -> str | None:
        if self._device.under_voltage is None:
            return None
        return "ON" if self._device.under_voltage else "OFF"


# --- Manufacturer Name ---


class SomaBleManufacturerNameSensor(_DiagnosticSensor):
    """Device manufacturer name."""

    _attr_name = "Manufacturer name"

    def __init__(self, device: Any, entry_id: str) -> None:
        super().__init__(device, entry_id, "manufacturer_name")

    @property
    def native_value(self) -> str | None:
        return self._device.manufacturer_name

    async def _initial_read(self) -> None:
        val = await self._device.read_manufacturer_name()
        if val is not None:
            self.async_write_ha_state()


# --- Hardware Revision ---


class SomaBleHardwareRevisionSensor(_DiagnosticSensor):
    """Device hardware revision."""

    _attr_name = "Hardware revision"

    def __init__(self, device: Any, entry_id: str) -> None:
        super().__init__(device, entry_id, "hardware_revision")

    @property
    def native_value(self) -> str | None:
        return self._device.hardware_revision

    async def _initial_read(self) -> None:
        val = await self._device.read_hardware_revision()
        if val is not None:
            self.async_write_ha_state()


# --- Software Revision ---


class SomaBleSoftwareRevisionSensor(_DiagnosticSensor):
    """Device software revision."""

    _attr_name = "Software revision"

    def __init__(self, device: Any, entry_id: str) -> None:
        super().__init__(device, entry_id, "software_revision")

    @property
    def native_value(self) -> str | None:
        return self._device.software_revision

    async def _initial_read(self) -> None:
        val = await self._device.read_software_revision()
        if val is not None:
            self.async_write_ha_state()
