"""The wrapper light: the source light plus one effect list of gradients."""

from __future__ import annotations

import time
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_MODE,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ATTR_HS_COLOR,
    ATTR_MAX_COLOR_TEMP_KELVIN,
    ATTR_MIN_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ATTR_RGBWW_COLOR,
    ATTR_SUPPORTED_COLOR_MODES,
    ATTR_TRANSITION,
    ATTR_XY_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Context, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device import async_entity_id_to_device
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity

from .backends import Backend
from .const import DOMAIN, EFFECT_SOLID, SETTLE_SECONDS, SIGNAL_CATALOGUE_UPDATED
from .data import GradientEffectsData

COLOUR_ATTRS = (
    ATTR_HS_COLOR,
    ATTR_XY_COLOR,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ATTR_RGBWW_COLOR,
    ATTR_COLOR_TEMP_KELVIN,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = entry.runtime_data
    # Show the wrapper on the source light's device page, named like the device.
    device = async_entity_id_to_device(hass, runtime.backend.source)
    light = GradientLight(entry, runtime.data, runtime.backend, device)
    runtime.light = light  # the reverse switch re-applies through it
    async_add_entities([light])


class GradientLight(LightEntity, RestoreEntity):
    """Mirrors the source light; effects are gradients, Solid, or the device's own."""

    _attr_should_poll = False

    def __init__(
        self,
        entry: ConfigEntry,
        data: GradientEffectsData,
        backend: Backend,
        device: dr.DeviceEntry | None,
    ) -> None:
        self._entry = entry
        self._data = data
        self._backend = backend
        self._attr_unique_id = entry.entry_id
        if device is not None:
            self.device_entry = device
            self._attr_has_entity_name = True
            self._attr_name = None
        else:
            self._attr_name = entry.title
        self._effect: str | None = None
        self._settle_until = 0.0
        self._colour_snapshot: tuple | None = None

    # --- lifecycle ---------------------------------------------------------------

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        if (last := await self.async_get_last_state()) is not None:
            effect = last.attributes.get(ATTR_EFFECT)
            if effect in self.effect_list:
                self._effect = effect

        self.async_on_remove(
            async_track_state_change_event(self.hass, [self._backend.source], self._source_changed)
        )
        scene_select = getattr(self._backend, "scene_select", None)
        if scene_select:
            self.async_on_remove(
                async_track_state_change_event(self.hass, [scene_select], self._scene_select_changed)
            )
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_CATALOGUE_UPDATED, self._catalogue_updated)
        )
        self._colour_snapshot = self._colour_key()

    # --- source tracking ---------------------------------------------------------

    def _src(self):
        return self.hass.states.get(self._backend.source)

    def _colour_key(self) -> tuple | None:
        state = self._src()
        if state is None or state.state != STATE_ON:
            return None
        a = state.attributes
        xy = a.get(ATTR_XY_COLOR)
        return (a.get(ATTR_COLOR_MODE), tuple(round(v, 3) for v in xy) if xy else None, a.get(ATTR_COLOR_TEMP_KELVIN))

    @callback
    def _source_changed(self, event: Event[EventStateChangedData]) -> None:
        old, new = event.data["old_state"], event.data["new_state"]
        colour = self._colour_key()
        if (
            self._effect is not None
            and time.monotonic() > self._settle_until
            and old is not None
            and new is not None
            and old.state == STATE_ON
            and new.state == STATE_ON
            and colour != self._colour_snapshot
        ):
            # Someone changed the colour outside this entity: the gradient is gone.
            self._effect = None
        self._colour_snapshot = colour
        self.async_write_ha_state()

    @callback
    def _scene_select_changed(self, event: Event[EventStateChangedData]) -> None:
        """A gradient scene chosen on the z2m select directly still shows here."""
        new = event.data["new_state"]
        if new is None or new.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        if time.monotonic() <= self._settle_until:
            return
        gradient = self._data.catalogue.by_key(f"hue:{new.state}")
        if gradient is not None:
            self._effect = gradient.label
            self._settle_until = time.monotonic() + SETTLE_SECONDS
            self.async_write_ha_state()

    @callback
    def _catalogue_updated(self) -> None:
        if self._effect is not None and self._effect not in self.effect_list:
            self._effect = None
        self.async_write_ha_state()

    # --- state -------------------------------------------------------------------

    @property
    def available(self) -> bool:
        state = self._src()
        return state is not None and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)

    @property
    def is_on(self) -> bool | None:
        state = self._src()
        return None if state is None else state.state == STATE_ON

    def _attr(self, key: str) -> Any:
        state = self._src()
        return state.attributes.get(key) if state else None

    @property
    def brightness(self) -> int | None:
        return self._attr(ATTR_BRIGHTNESS)

    @property
    def supported_color_modes(self) -> set[ColorMode] | None:
        modes = self._attr(ATTR_SUPPORTED_COLOR_MODES)
        return {ColorMode(m) for m in modes} if modes else {ColorMode.ONOFF}

    @property
    def color_mode(self) -> ColorMode | None:
        mode = self._attr(ATTR_COLOR_MODE)
        return ColorMode(mode) if mode else None

    @property
    def hs_color(self):
        return self._attr(ATTR_HS_COLOR)

    @property
    def xy_color(self):
        return self._attr(ATTR_XY_COLOR)

    @property
    def rgb_color(self):
        return self._attr(ATTR_RGB_COLOR)

    @property
    def rgbw_color(self):
        return self._attr(ATTR_RGBW_COLOR)

    @property
    def rgbww_color(self):
        return self._attr(ATTR_RGBWW_COLOR)

    @property
    def color_temp_kelvin(self) -> int | None:
        return self._attr(ATTR_COLOR_TEMP_KELVIN)

    @property
    def min_color_temp_kelvin(self) -> int:
        return self._attr(ATTR_MIN_COLOR_TEMP_KELVIN) or 2000

    @property
    def max_color_temp_kelvin(self) -> int:
        return self._attr(ATTR_MAX_COLOR_TEMP_KELVIN) or 6500

    @property
    def supported_features(self) -> LightEntityFeature:
        return LightEntityFeature.EFFECT | LightEntityFeature.TRANSITION

    @property
    def effect_list(self) -> list[str]:
        gradients = self._data.catalogue.labels()
        native = [label for label in self._backend.native_effects if label not in gradients]
        return [EFFECT_SOLID, *gradients, *native]

    @property
    def effect(self) -> str | None:
        return self._effect

    # --- control -----------------------------------------------------------------

    async def async_turn_on(self, **kwargs: Any) -> None:
        """One call carries everything a scene replays: effect, colour and brightness."""
        context = self._context or Context()
        effect = kwargs.pop(ATTR_EFFECT, None)
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        colour = {k: kwargs[k] for k in COLOUR_ATTRS if k in kwargs}
        self._settle_until = time.monotonic() + SETTLE_SECONDS

        if effect is not None:
            if effect == EFFECT_SOLID:
                await self._backend.apply_solid(colour, brightness, context)
                self._effect = None
            elif (gradient := self._data.catalogue.by_label(effect)) is not None:
                # A gradient wins over any colour in the same call (scene snapshots
                # always carry one).
                await self._backend.apply_gradient(gradient, brightness, context)
                self._effect = effect
            elif effect in self._backend.native_effects:
                await self._backend.apply_native_effect(self._backend.native_effects[effect], brightness, context)
                self._effect = effect
            else:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="unknown_effect",
                    translation_placeholders={"effect": effect},
                )
        elif colour:
            await self._backend.apply_solid(colour, brightness, context)
            self._effect = None
        else:
            data = {k: kwargs[k] for k in (ATTR_BRIGHTNESS, ATTR_TRANSITION) if k in kwargs}
            await self._backend.turn_on(data, context)

        self.async_write_ha_state()

    async def async_reapply(self) -> None:
        """Re-send the current gradient (e.g. after its direction changed)."""
        if not self.is_on or self._effect is None:
            return
        gradient = self._data.catalogue.by_label(self._effect)
        if gradient is None:  # Solid / device effects have no direction
            return
        self._settle_until = time.monotonic() + SETTLE_SECONDS
        await self._backend.apply_gradient(gradient, None, Context())

    async def async_turn_off(self, **kwargs: Any) -> None:
        data = {ATTR_TRANSITION: kwargs[ATTR_TRANSITION]} if ATTR_TRANSITION in kwargs else {}
        await self._backend.turn_off(data, self._context or Context())
