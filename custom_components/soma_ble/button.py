"""Button platform for SOMA BLE blinds.

Control buttons: step up, step down.
Diagnostic buttons: refresh shade config.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, MODEL


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the SOMA BLE button entities."""
    device = hass.data[DOMAIN][entry.entry_id]["device"]
    async_add_entities([
        SomaBleStepUpButton(device, entry.entry_id),
        SomaBleStepDownButton(device, entry.entry_id),
        SomaBleRefreshShadeConfigButton(device, entry.entry_id),
    ])


def _device_info(device: Any) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, device.unique_id)},
        name=device.name,
        manufacturer=MANUFACTURER,
        model=MODEL,
        connections={("mac", device.mac)},
    )


class _ControlButton(ButtonEntity):
    """Base for control buttons."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, device: Any, entry_id: str, suffix: str) -> None:
        self._device = device
        self._attr_unique_id = f"{entry_id}_{suffix}"
        self._attr_device_info = _device_info(device)

    @property
    def available(self) -> bool:
        return self._device.online


class SomaBleStepUpButton(_ControlButton):
    """Button to step the blind up one increment."""

    _attr_name = "Step up"

    def __init__(self, device: Any, entry_id: str) -> None:
        super().__init__(device, entry_id, "step_up")

    async def async_press(self) -> None:
        await self._device.step_up()


class SomaBleStepDownButton(_ControlButton):
    """Button to step the blind down one increment."""

    _attr_name = "Step down"

    def __init__(self, device: Any, entry_id: str) -> None:
        super().__init__(device, entry_id, "step_down")

    async def async_press(self) -> None:
        await self._device.step_down()


class SomaBleRefreshShadeConfigButton(ButtonEntity):
    """Button to trigger a shade config re-read via BLE."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Refresh shade config"

    def __init__(self, device: Any, entry_id: str) -> None:
        self._device = device
        self._attr_unique_id = f"{entry_id}_refresh_shade_config"
        self._attr_device_info = _device_info(device)

    @property
    def available(self) -> bool:
        return self._device.online

    async def async_press(self) -> None:
        await self._device.force_refresh_shade_config()
