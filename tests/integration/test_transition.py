"""`transition` must reach the strip on every turn_on path, not just plain brightness."""

from __future__ import annotations

import json

from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_mock_service
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from . import test_hue, test_wled


def entity(hass: HomeAssistant, entity_id: str):
    return hass.data["entity_components"][LIGHT_DOMAIN].get_entity(entity_id)


async def test_wled_gradient_one_off_transition(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, wled_source
):
    test_wled.mock_controller(aioclient_mock)
    wrapper = await test_wled.add_strip(hass, wled_source)
    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": wrapper, "effect": "Vapor Wave", "brightness": 120, "transition": 3},
        blocking=True,
    )
    posted = test_wled.calls(aioclient_mock, "POST", "/json/state")[-1][2]
    assert posted["tt"] == 30 and posted["bri"] == 120
    assert "transition" not in posted  # would change the controller's default fade


async def test_hue_gradient_with_transition_uses_explicit_gradient(hass: HomeAssistant, hue_source):
    """gradient_scene has a fixed fade, so a transition switches to z2m's `gradient`
    command with state/brightness/transition in one message."""
    light, _ = hue_source
    wrapper = await test_hue.add_strip(hass, light)
    select_calls = async_mock_service(hass, "select", "select_option")
    mqtt_calls = async_mock_service(hass, "mqtt", "publish")

    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": wrapper, "effect": "Vapor Wave", "brightness": 150, "transition": 2.5},
        blocking=True,
    )
    assert not select_calls
    payload = json.loads(mqtt_calls[0].data["payload"])
    assert payload["transition"] == 2.5 and payload["brightness"] == 150 and payload["state"] == "ON"
    # Forwards: pre-flipped, because z2m flips the list for Hue gradient lights.
    assert payload["gradient"] == test_hue.vapor_wave().z2m_hex(reverse=True)


async def test_hue_gradient_without_transition_keeps_native_recall(hass: HomeAssistant, hue_source):
    light, _ = hue_source
    wrapper = await test_hue.add_strip(hass, light)
    select_calls = async_mock_service(hass, "select", "select_option")
    mqtt_calls = async_mock_service(hass, "mqtt", "publish")
    await hass.services.async_call("light", "turn_on", {"entity_id": wrapper, "effect": "Vapor Wave"}, blocking=True)
    assert [c.data["option"] for c in select_calls] == ["vapor_wave"]
    assert not mqtt_calls


async def test_colour_and_native_effect_forward_transition(hass: HomeAssistant, hue_source):
    light, _ = hue_source
    wrapper = await test_hue.add_strip(hass, light)
    # Capture calls the wrapper makes against the source light. Call the entity
    # directly, because mocking light.turn_on would also swallow the wrapper itself.
    light_calls = async_mock_service(hass, "light", "turn_on")
    lamp = entity(hass, wrapper)

    await lamp.async_turn_on(rgb_color=(0, 0, 255), brightness=90, transition=4)
    await lamp.async_turn_on(effect="Candle", transition=1.5)

    colour_call, effect_call = light_calls[-2], light_calls[-1]
    assert colour_call.data["entity_id"] == light
    assert colour_call.data["transition"] == 4 and colour_call.data["brightness"] == 90
    assert effect_call.data["effect"] == "candle" and effect_call.data["transition"] == 1.5
