"""Config and options flows: add strips, and edit the custom gradient library."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    BooleanSelector,
    ColorRGBSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
)

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
    DEFAULT_Z2M_BASE_TOPIC,
    DOMAIN,
    KIND_LIBRARY,
    KIND_STRIP,
)
from .data import async_get_data
from .gradients import MAX_COLOURS, MIN_COLOURS

LIBRARY_UNIQUE_ID = "library"
COLOUR_KEYS = [f"colour_{i}" for i in range(1, MAX_COLOURS + 1)]


class DetectError(Exception):
    """The chosen light isn't a supported strip; args[0] is the error key."""


def detect_backend(hass: HomeAssistant, entity_id: str) -> dict[str, Any]:
    """Work out how to drive ``entity_id`` from the entity and device registries."""
    ent_reg = er.async_get(hass)
    entry = ent_reg.async_get(entity_id)
    if entry is None:
        raise DetectError("not_found")

    if entry.platform == "wled":
        source_entry = hass.config_entries.async_get_entry(entry.config_entry_id or "")
        host = source_entry.data.get(CONF_HOST) if source_entry else None
        if not host:
            raise DetectError("wled_no_host")
        # WLED segment lights have unique ids "<mac>_<segment>"; the main light is "<mac>".
        tail = entry.unique_id.rsplit("_", 1)[-1]
        segment = int(tail) if "_" in entry.unique_id and tail.isdigit() else 0
        return {CONF_BACKEND: BACKEND_WLED, CONF_HOST: host, CONF_SEGMENT: segment}

    if entry.platform == "mqtt" and entry.device_id:
        device = dr.async_get(hass).async_get(entry.device_id)
        if device is None or not any(
            domain == "mqtt" and ident.startswith("zigbee2mqtt_") for domain, ident in device.identifiers
        ):
            raise DetectError("not_z2m")
        scene_select = next(
            (
                e.entity_id
                for e in er.async_entries_for_device(ent_reg, entry.device_id)
                if e.domain == "select"
                and (e.unique_id.endswith("_gradient_scene_zigbee2mqtt") or e.entity_id.endswith("_gradient_scene"))
            ),
            None,
        )
        if scene_select is None:
            raise DetectError("not_gradient")
        return {
            CONF_BACKEND: BACKEND_HUE_Z2M,
            CONF_SCENE_SELECT: scene_select,
            CONF_MQTT_TOPIC: f"{DEFAULT_Z2M_BASE_TOPIC}/{device.name}",
        }

    raise DetectError("unsupported")


class GradientEffectsConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._source: str | None = None
        self._detected: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        if config_entry.data.get(CONF_KIND) == KIND_LIBRARY:
            return LibraryOptionsFlow()
        return StripOptionsFlow()

    def _has_library(self) -> bool:
        return any(e.unique_id == LIBRARY_UNIQUE_ID for e in self._async_current_entries())

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._has_library():
            return await self.async_step_strip()
        return self.async_show_menu(step_id="user", menu_options=["strip", "library"])

    async def async_step_library(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(LIBRARY_UNIQUE_ID)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="Gradient library", data={CONF_KIND: KIND_LIBRARY})

    async def async_step_strip(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            source = user_input[CONF_SOURCE]
            try:
                self._detected = detect_backend(self.hass, source)
            except DetectError as err:
                errors[CONF_SOURCE] = err.args[0]
            else:
                registry_id = er.async_get(self.hass).async_get(source).id  # stable across renames
                await self.async_set_unique_id(registry_id)
                self._abort_if_unique_id_configured()
                self._source = source
                return await self.async_step_settings()

        own = [e.entity_id for e in er.async_get(self.hass).entities.values() if e.platform == DOMAIN]
        schema = vol.Schema(
            {vol.Required(CONF_SOURCE): EntitySelector(EntitySelectorConfig(domain="light", exclude_entities=own))}
        )
        return self.async_show_form(step_id="strip", data_schema=schema, errors=errors)

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._source is not None
        if user_input is not None:
            state = self.hass.states.get(self._source)
            title = state.name if state else self._source
            data = {CONF_KIND: KIND_STRIP, CONF_SOURCE: self._source, **self._detected}
            return self.async_create_entry(title=title, data=data, options=user_input)
        return self.async_show_form(
            step_id="settings",
            data_schema=_strip_schema(self._detected[CONF_BACKEND], {**self._detected}),
            description_placeholders={"backend": _backend_name(self._detected[CONF_BACKEND])},
        )


def _backend_name(backend: str) -> str:
    return {BACKEND_HUE_Z2M: "Hue gradient (Zigbee2MQTT)", BACKEND_WLED: "WLED"}.get(backend, backend)


def _strip_schema(backend: str, current: dict[str, Any], *, include_reverse: bool = True) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if include_reverse:  # afterwards it's the "Reverse gradient" switch on the device
        fields[vol.Required(CONF_REVERSE, default=bool(current.get(CONF_REVERSE, False)))] = BooleanSelector()
    if backend == BACKEND_HUE_Z2M:
        fields[vol.Required(CONF_MQTT_TOPIC, default=current.get(CONF_MQTT_TOPIC, ""))] = TextSelector()
    if backend == BACKEND_WLED:
        fields[vol.Required(CONF_SEGMENT, default=int(current.get(CONF_SEGMENT, 0)))] = NumberSelector(
            NumberSelectorConfig(min=0, max=31, step=1, mode=NumberSelectorMode.BOX)
        )
    return vol.Schema(fields)


class StripOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            if CONF_SEGMENT in user_input:
                user_input[CONF_SEGMENT] = int(user_input[CONF_SEGMENT])
            # Keep options this form doesn't show (reverse lives on the device switch).
            return self.async_create_entry(data={**self.config_entry.options, **user_input})
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init", data_schema=_strip_schema(current[CONF_BACKEND], current, include_reverse=False)
        )


class LibraryOptionsFlow(OptionsFlow):
    """Add / edit / delete custom gradients."""

    def __init__(self) -> None:
        self._editing: str | None = None

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        data = await async_get_data(self.hass)
        options = ["add"] + (["edit", "delete"] if data.custom else [])
        return self.async_show_menu(step_id="init", menu_options=options)

    def _gradient_choices(self, data) -> SelectSelector:
        return SelectSelector(
            SelectSelectorConfig(options=[{"value": g["id"], "label": g["name"]} for g in data.custom])
        )

    async def async_step_add(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._editing = None
        return await self._gradient_form("add", user_input, {})

    async def async_step_edit(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        data = await async_get_data(self.hass)
        if user_input is not None:
            self._editing = user_input["gradient"]
            return await self.async_step_edit_colours()
        return self.async_show_form(
            step_id="edit", data_schema=vol.Schema({vol.Required("gradient"): self._gradient_choices(data)})
        )

    async def async_step_edit_colours(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        data = await async_get_data(self.hass)
        existing = data.custom_gradient(self._editing or "") or {}
        return await self._gradient_form("edit_colours", user_input, existing)

    async def _gradient_form(
        self, step_id: str, user_input: dict[str, Any] | None, existing: dict[str, Any]
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            colours = [list(user_input[k]) for k in COLOUR_KEYS if user_input.get(k)]
            name = str(user_input.get("name", "")).strip()
            if not name:
                errors["name"] = "name_required"
            elif not MIN_COLOURS <= len(colours) <= MAX_COLOURS:
                errors["base"] = "colour_count"
            else:
                data = await async_get_data(self.hass)
                await data.async_save_custom(name, colours, self._editing)
                return self.async_create_entry(data={})

        existing_colours = existing.get("colours", [])
        fields: dict[Any, Any] = {vol.Required("name", default=existing.get("name", "")): TextSelector()}
        for i, key in enumerate(COLOUR_KEYS):
            default = existing_colours[i] if i < len(existing_colours) else None
            marker = vol.Optional(key, default=default) if default else vol.Optional(key)
            fields[marker] = ColorRGBSelector()
        return self.async_show_form(step_id=step_id, data_schema=vol.Schema(fields), errors=errors)

    async def async_step_delete(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        data = await async_get_data(self.hass)
        if user_input is not None:
            await data.async_delete_custom(user_input["gradient"])
            return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="delete", data_schema=vol.Schema({vol.Required("gradient"): self._gradient_choices(data)})
        )
