"""Gradient Effects: one effect list of gradients for Hue gradient and WLED strips."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .backends import Backend, HueZ2MBackend, WledBackend
from .const import (
    BACKEND_HUE_Z2M,
    BACKEND_WLED,
    CONF_BACKEND,
    CONF_HOST,
    CONF_KIND,
    CONF_MQTT_TOPIC,
    CONF_REVERSE,
    CONF_SCENE_SELECT,
    CONF_SEGMENT,
    CONF_SOURCE,
    DOMAIN,
    KIND_LIBRARY,
)
from .data import GradientEffectsData, async_get_data

if TYPE_CHECKING:
    from .light import GradientLight

PLATFORMS = [Platform.LIGHT, Platform.SWITCH]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Options that can change live, without reloading the entry.
LIVE_OPTIONS = {CONF_REVERSE}


@dataclass
class StripRuntime:
    data: GradientEffectsData
    backend: Backend
    light: GradientLight | None = None
    reload_options: dict[str, Any] = field(default_factory=dict)

    async def async_set_reverse(self, hass: HomeAssistant, entry: ConfigEntry, reverse: bool) -> None:
        """Flip the gradient direction now and remember it (no reload)."""
        self.backend.reverse = reverse
        hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_REVERSE: reverse})
        if self.light is not None:
            await self.light.async_reapply()


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    await async_get_data(hass)
    return True


def _build_backend(hass: HomeAssistant, entry: ConfigEntry, data: GradientEffectsData) -> Backend:
    conf = {**entry.data, **entry.options}
    reverse = bool(conf.get(CONF_REVERSE, False))
    if conf[CONF_BACKEND] == BACKEND_HUE_Z2M:
        return HueZ2MBackend(
            hass, conf[CONF_SOURCE], reverse, conf.get(CONF_SCENE_SELECT), conf[CONF_MQTT_TOPIC]
        )
    if conf[CONF_BACKEND] == BACKEND_WLED:
        return WledBackend(
            hass,
            conf[CONF_SOURCE],
            reverse,
            data.controller(conf[CONF_HOST]),
            int(conf.get(CONF_SEGMENT, 0)),
            data.known_hashes,
        )
    raise ValueError(f"unknown backend {conf[CONF_BACKEND]}")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = await async_get_data(hass)
    if entry.data.get(CONF_KIND) == KIND_LIBRARY:
        # The library entry only hosts the custom-gradient editor (its options flow).
        return True

    backend = _build_backend(hass, entry, data)
    entry.runtime_data = StripRuntime(data=data, backend=backend, reload_options=_reload_options(entry))
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    if isinstance(backend, WledBackend):
        entry.async_create_background_task(hass, backend.prepare(), f"{DOMAIN} warm palette cache")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if entry.data.get(CONF_KIND) == KIND_LIBRARY:
        return True
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _reload_options(entry: ConfigEntry) -> dict[str, Any]:
    return {k: v for k, v in entry.options.items() if k not in LIVE_OPTIONS}


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload for structural changes (topic, segment); live ones are already applied."""
    runtime: StripRuntime = entry.runtime_data
    if _reload_options(entry) != runtime.reload_options:
        await hass.config_entries.async_reload(entry.entry_id)
