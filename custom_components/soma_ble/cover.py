"""Cover platform for SOMA BLE blinds.

Entity state is driven by BLE advertisements (no polling).
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
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
    """Set up the SOMA BLE cover."""
    device = hass.data[DOMAIN][entry.entry_id]["device"]
    async_add_entities([SomaBleCover(device, entry.entry_id)], False)


class SomaBleCover(CoverEntity):
    """SOMA blind cover."""

    _attr_device_class = CoverDeviceClass.BLIND
    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    def __init__(self, device: Any, entry_id: str) -> None:
        """Initialize the cover."""
        self._device = device
        self._attr_unique_id = f"{entry_id}_cover"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.unique_id)},
            name=device.name,
            manufacturer=MANUFACTURER,
            model=MODEL,
            connections={("mac", device.mac)},
        )

    # --- State ---

    @property
    def current_cover_position(self) -> int | None:
        return self._device.position

    @property
    def is_closed(self) -> bool | None:
        pos = self._device.position
        if pos is None:
            return None
        return pos <= 0

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
        """Called by the device when a new advertisement is parsed."""
        self.async_write_ha_state()

    # --- Commands ---

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the blind."""
        await self._device.open()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the blind."""
        await self._device.close()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the blind."""
        await self._device.stop()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set the blind to a specific position."""
        await self._device.set_position(kwargs["position"])
