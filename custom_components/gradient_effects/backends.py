"""Backends: how a gradient (or a plain colour) is put onto each kind of strip."""

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_MODE,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ATTR_EFFECT_LIST,
    ATTR_XY_COLOR,
    ColorMode,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_ON
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import EFFECT_SOLID, HUE_HIDDEN_EFFECTS
from .gradients import Gradient
from .wled import WledController, WledError

_LOGGER = logging.getLogger(__name__)


def _label(raw: str) -> str:
    return raw.replace("_", " ").title()


class Backend:
    """Common plumbing: the wrapped light entity and service calls against it."""

    def __init__(self, hass: HomeAssistant, source: str, reverse: bool) -> None:
        self.hass = hass
        self.source = source
        self.reverse = reverse

    def _state(self):
        return self.hass.states.get(self.source)

    def is_on(self) -> bool:
        state = self._state()
        return state is not None and state.state == STATE_ON

    async def _light(self, service: str, context: Context, **data: Any) -> None:
        await self.hass.services.async_call(
            "light", service, {ATTR_ENTITY_ID: self.source, **data}, blocking=True, context=context
        )

    # Overridden per backend -------------------------------------------------------

    @property
    def native_effects(self) -> dict[str, str]:
        """Device effects to offer alongside gradients: {label: raw effect}."""
        return {}

    async def apply_gradient(self, gradient: Gradient, brightness: int | None, context: Context) -> None:
        raise NotImplementedError

    async def apply_native_effect(self, raw: str, brightness: int | None, context: Context) -> None:
        await self._light("turn_on", context, **_bri(brightness), effect=raw)

    async def apply_solid(self, colour: dict[str, Any], brightness: int | None, context: Context) -> None:
        """Plain colour. With no colour given, flatten to the strip's current colour."""
        await self._light("turn_on", context, **_bri(brightness), **(colour or self._current_colour()))

    async def turn_on(self, data: dict[str, Any], context: Context) -> None:
        await self._light("turn_on", context, **data)

    async def turn_off(self, data: dict[str, Any], context: Context) -> None:
        await self._light("turn_off", context, **data)

    def _current_colour(self) -> dict[str, Any]:
        state = self._state()
        attrs = state.attributes if state else {}
        if attrs.get(ATTR_COLOR_MODE) == ColorMode.COLOR_TEMP and attrs.get(ATTR_COLOR_TEMP_KELVIN):
            return {ATTR_COLOR_TEMP_KELVIN: attrs[ATTR_COLOR_TEMP_KELVIN]}
        if attrs.get(ATTR_XY_COLOR):
            return {ATTR_XY_COLOR: attrs[ATTR_XY_COLOR]}
        return {ATTR_COLOR_TEMP_KELVIN: 2700}


class HueZ2MBackend(Backend):
    """Philips Hue gradient strip via Zigbee2MQTT."""

    def __init__(
        self,
        hass: HomeAssistant,
        source: str,
        reverse: bool,
        scene_select: str | None,
        mqtt_topic: str,
    ) -> None:
        super().__init__(hass, source, reverse)
        self.scene_select = scene_select
        self.mqtt_topic = mqtt_topic.rstrip("/")

    @property
    def native_effects(self) -> dict[str, str]:
        state = self._state()
        raw = (state.attributes.get(ATTR_EFFECT_LIST) if state else None) or []
        return {_label(e): e for e in raw if e not in HUE_HIDDEN_EFFECTS}

    def _scene_option_available(self, gradient: Gradient) -> bool:
        if not self.scene_select or gradient.hue_scene is None:
            return False
        state = self.hass.states.get(self.scene_select)
        return state is not None and gradient.hue_scene in (state.attributes.get("options") or [])

    async def apply_gradient(self, gradient: Gradient, brightness: int | None, context: Context) -> None:
        if not self.reverse and self._scene_option_available(gradient):
            # Native scene recall: exactly what the Hue app would do.
            if not self.is_on():
                await self._light("turn_on", context, **_bri(brightness))
            await self.hass.services.async_call(
                "select",
                "select_option",
                {ATTR_ENTITY_ID: self.scene_select, "option": gradient.hue_scene},
                blocking=True,
                context=context,
            )
            if brightness is not None:
                await self._light("turn_on", context, brightness=brightness)
            return

        # Reversed or custom: send the colour points explicitly via z2m's `gradient`.
        payload: dict[str, Any] = {"state": "ON", "gradient": gradient.z2m_hex(reverse=self.reverse)}
        if brightness is not None:
            payload["brightness"] = brightness
        # Via the service rather than importing the mqtt component, so WLED-only
        # installs (no paho-mqtt) can still load this module.
        await self.hass.services.async_call(
            "mqtt",
            "publish",
            {"topic": f"{self.mqtt_topic}/set", "payload": json.dumps(payload)},
            blocking=True,
            context=context,
        )

    async def apply_solid(self, colour: dict[str, Any], brightness: int | None, context: Context) -> None:
        state = self._state()
        if state is not None and state.attributes.get(ATTR_EFFECT) not in (None, "none"):
            await self._light("turn_on", context, effect="stop_hue_effect")
        await super().apply_solid(colour, brightness, context)


class WledBackend(Backend):
    """WLED strip: gradients become custom palettes shown with the Palette effect."""

    def __init__(
        self,
        hass: HomeAssistant,
        source: str,
        reverse: bool,
        controller: WledController,
        segment: int,
        known_hashes,
    ) -> None:
        super().__init__(hass, source, reverse)
        self.controller = controller
        self.segment = segment
        self._known_hashes = known_hashes  # callable -> set[str]

    async def apply_gradient(self, gradient: Gradient, brightness: int | None, context: Context) -> None:
        try:
            palette_id = await self.controller.ensure_palette(gradient.wled_palette(), self._known_hashes())
            await self.controller.show_palette(
                self.segment, palette_id, reverse=self.reverse, brightness=brightness
            )
        except WledError as err:
            raise HomeAssistantError(f"WLED {self.controller.host}: {err}") from err
        await self._refresh()

    async def apply_solid(self, colour: dict[str, Any], brightness: int | None, context: Context) -> None:
        # The WLED integration keeps the current effect when only a colour is sent,
        # so switch back to Solid in the same call.
        await self._light(
            "turn_on", context, **_bri(brightness), effect=EFFECT_SOLID, **(colour or self._current_colour())
        )

    async def _refresh(self) -> None:
        """Changes made over the JSON API aren't pushed to the WLED integration's
        coordinator straight away; ask it to poll."""
        if not self.hass.services.has_service("homeassistant", "update_entity"):
            return
        await self.hass.services.async_call(
            "homeassistant", "update_entity", {ATTR_ENTITY_ID: self.source}, blocking=False
        )


def _bri(brightness: int | None) -> dict[str, Any]:
    return {} if brightness is None else {ATTR_BRIGHTNESS: brightness}
