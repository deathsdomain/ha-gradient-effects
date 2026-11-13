"""Per-strip "Reverse gradient" switch, shown on the strip's device page."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device import async_entity_id_to_device
from homeassistant.helpers.entity_platform import AddEntitiesCallback


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([ReverseSwitch(hass, entry)])


class ReverseSwitch(SwitchEntity):
    """Runs every gradient the other way along this strip; flips the current one live."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False
    _attr_translation_key = "reverse"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._entry = entry
        self._runtime = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_reverse"
        device = async_entity_id_to_device(hass, self._runtime.backend.source)
        if device is not None:
            self.device_entry = device
            self._attr_has_entity_name = True
        else:
            self._attr_name = f"{entry.title} reverse gradient"

    @property
    def is_on(self) -> bool:
        return self._runtime.backend.reverse

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, reverse: bool) -> None:
        await self._runtime.async_set_reverse(self.hass, self._entry, reverse)
        self.async_write_ha_state()
