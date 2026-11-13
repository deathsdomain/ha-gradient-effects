"""The per-strip "Reverse gradient" switch: live flip, persisted, no reload."""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_mock_service
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.gradient_effects.const import DOMAIN

from . import test_hue, test_wled


def reverse_switch(hass: HomeAssistant, entry_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id("switch", DOMAIN, f"{entry_id}_reverse")
    assert entity_id is not None
    return entity_id


async def test_wled_flip_live(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, wled_source):
    test_wled.mock_controller(aioclient_mock)
    wrapper = await test_wled.add_strip(hass, wled_source)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    switch = reverse_switch(hass, entry.entry_id)
    assert hass.states.get(switch).state == "off"

    await hass.services.async_call("light", "turn_on", {"entity_id": wrapper, "effect": "Blossom"}, blocking=True)
    posts_before = len(test_wled.calls(aioclient_mock, "POST", "/json/state"))

    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    await hass.async_block_till_done()

    posts = test_wled.calls(aioclient_mock, "POST", "/json/state")
    assert len(posts) == posts_before + 1
    seg = posts[-1][2]["seg"][0]
    assert seg["rev"] is True and seg["pal"] == 200  # same palette, cache hit
    assert "bri" not in posts[-1][2]  # brightness left alone
    assert hass.states.get(switch).state == "on"
    assert entry.options["reverse"] is True
    # No reload: the light kept its effect.
    assert hass.states.get(wrapper).attributes["effect"] == "Blossom"


async def test_flip_when_solid_does_nothing(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, wled_source
):
    test_wled.mock_controller(aioclient_mock)
    await test_wled.add_strip(hass, wled_source)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": reverse_switch(hass, entry.entry_id)}, blocking=True
    )
    assert not test_wled.calls(aioclient_mock, "POST", "/json/state")
    assert entry.options["reverse"] is True


async def test_hue_flip_sends_reversed_gradient(hass: HomeAssistant, hue_source):
    light, _ = hue_source
    wrapper = await test_hue.add_strip(hass, light)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    async_mock_service(hass, "select", "select_option")
    mqtt_calls = async_mock_service(hass, "mqtt", "publish")

    await hass.services.async_call("light", "turn_on", {"entity_id": wrapper, "effect": "Vapor Wave"}, blocking=True)
    hass.states.async_set(light, "on", {**hass.states.get(light).attributes, "color_mode": "xy",
                                        "xy_color": (0.2, 0.1), "brightness": 150})
    await hass.async_block_till_done()
    assert not mqtt_calls  # forwards: native scene recall

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": reverse_switch(hass, entry.entry_id)}, blocking=True
    )
    payload = json.loads(mqtt_calls[-1].data["payload"])
    assert payload["gradient"][0].startswith("#") and len(payload["gradient"]) == 5
    assert "brightness" not in payload


async def test_options_form_keeps_reverse(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, wled_source):
    test_wled.mock_controller(aioclient_mock)
    await test_wled.add_strip(hass, wled_source, reverse=True)
    entry = hass.config_entries.async_entries(DOMAIN)[0]

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "reverse" not in result["data_schema"].schema
    await hass.config_entries.options.async_configure(result["flow_id"], {"segment": 0})
    await hass.async_block_till_done()
    assert entry.options["reverse"] is True
