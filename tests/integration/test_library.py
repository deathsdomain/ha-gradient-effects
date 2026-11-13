"""Custom gradient library: add / edit / delete via the options flow."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.gradient_effects.const import DOMAIN

from .test_hue import add_strip


async def add_library(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "library"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    return result["result"].entry_id


async def options(hass: HomeAssistant, entry_id: str, step: str, data: dict):
    result = await hass.config_entries.options.async_init(entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": step})
    return await hass.config_entries.options.async_configure(result["flow_id"], data)


async def test_add_edit_delete(hass: HomeAssistant, hue_source):
    library = await add_library(hass)
    light, _ = hue_source
    wrapper = await add_strip(hass, light)

    result = await options(
        hass, library, "add", {"name": "Warm Night", "colour_1": [255, 80, 0], "colour_2": [120, 0, 255]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    effects = hass.states.get(wrapper).attributes["effect_list"]
    assert effects[:2] == ["Solid", "Warm Night"]

    # Edit: rename and add a third colour.
    result = await options(hass, library, "edit", {"gradient": "warm_night"})
    assert result["step_id"] == "edit_colours"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"name": "Warmer Night", "colour_1": [255, 80, 0], "colour_2": [120, 0, 255], "colour_3": [0, 0, 255]},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert hass.states.get(wrapper).attributes["effect_list"][1] == "Warmer Night"

    result = await options(hass, library, "delete", {"gradient": "warm_night"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert "Warmer Night" not in hass.states.get(wrapper).attributes["effect_list"]


async def test_colour_count_validated(hass: HomeAssistant):
    library = await add_library(hass)
    result = await options(hass, library, "add", {"name": "Lonely", "colour_1": [255, 0, 0]})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "colour_count"}


async def test_second_library_skipped(hass: HomeAssistant):
    await add_library(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "strip"
