"""Config flow for SOMA BLE blinds."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_ADDRESS
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, MANUFACTURER_ID

_MANUAL_ENTRY = "manual"


def _parse_name_from_mfr(mfr_data: bytes) -> str | None:
    """Extract display name from manufacturer data."""
    data = mfr_data
    if len(data) >= 2 and data[0] == 0x70 and data[1] == 0x03:
        data = data[2:]
    if len(data) <= 4:
        return None
    name_bytes = data[4:]
    null = name_bytes.find(b"\x00")
    if null > 0:
        try:
            decoded = name_bytes[:null].decode("ascii")
            return decoded.strip() or None
        except UnicodeDecodeError:
            pass
    return None


def _shorten(address: str) -> str:
    """Last 8 hex chars of a MAC, uppercased."""
    return address[-8:].replace(":", "").upper()


def _validate_mac(address: str) -> bool:
    """Basic MAC address validation."""
    parts = address.split(":")
    return (
        len(parts) == 6
        and all(len(p) == 2 for p in parts)
        and all(_is_hex(p) for p in parts)
    )


def _is_hex(s: str) -> bool:
    try:
        int(s, 16)
        return True
    except ValueError:
        return False


class SomaBleConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SOMA BLE blinds."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle a flow initiated by Bluetooth discovery."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._discovery_info = discovery_info

        name = discovery_info.name or _shorten(discovery_info.address)

        # Try to get a better name from manufacturer data
        mfr_data = discovery_info.manufacturer_data.get(MANUFACTURER_ID)
        if mfr_data:
            parsed = _parse_name_from_mfr(mfr_data)
            if parsed:
                name = parsed

        self.context["title_placeholders"] = {"name": name}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm the discovered blind."""
        assert self._discovery_info
        address = self._discovery_info.address

        if user_input is not None:
            name = _parse_name_from_mfr(
                self._discovery_info.manufacturer_data.get(MANUFACTURER_ID, b"")
            ) or f"SOMA Blind {_shorten(address)}"
            return self.async_create_entry(
                title=name,
                data={
                    "mac": address,
                    "name": name,
                },
            )

        mfr_data = self._discovery_info.manufacturer_data.get(MANUFACTURER_ID, b"")
        name = _parse_name_from_mfr(mfr_data) or f"SOMA Blind {_shorten(address)}"

        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "name": name,
                "address": address,
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show discovered blinds or go to manual entry."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            if address == _MANUAL_ENTRY:
                return await self.async_step_manual()
            await self.async_set_unique_id(address, raise_on_proof=False)
            self._abort_if_unique_id_configured()

            # Build a name from discovery data if available
            info = self._discovered.get(address)
            name = f"SOMA Blind {_shorten(address)}"
            if info:
                mfr = info.manufacturer_data.get(MANUFACTURER_ID, b"")
                parsed = _parse_name_from_mfr(mfr)
                if parsed:
                    name = parsed

            return self.async_create_entry(
                title=name,
                data={"mac": address, "name": name},
            )

        # Scan for nearby SOMA devices
        discovered = async_discovered_service_info(self.hass)
        devices: dict[str, BluetoothServiceInfoBleak] = {}
        for info in discovered:
            if MANUFACTURER_ID in info.manufacturer_data:
                devices[info.address] = info

        self._discovered = devices

        if not devices:
            return await self.async_step_manual()

        options: dict[str, str] = {}
        for addr, info in devices.items():
            mfr = info.manufacturer_data.get(MANUFACTURER_ID, b"")
            label = _parse_name_from_mfr(mfr) or f"SOMA Blind {_shorten(addr)}"
            options[addr] = f"{label} ({addr})"

        options[_MANUAL_ENTRY] = "Enter MAC address manually..."

        schema = vol.Schema({vol.Required(CONF_ADDRESS): vol.In(options)})
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Enter a MAC address manually."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            if _validate_mac(address):
                await self.async_set_unique_id(address, raise_on_proof=False)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"SOMA Blind {_shorten(address)}",
                    data={
                        "mac": address,
                        "name": f"SOMA Blind {_shorten(address)}",
                    },
                )
            errors["base"] = "invalid_mac"

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): str}),
            errors=errors,
        )
