"""Hue gradient strip via Zigbee2MQTT: detection, scene recall and reversed/custom path."""

from __future__ import annotations

import json

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.gradient_effects.const import DOMAIN
from custom_components.gradient_effects.data import async_get_data
from custom_components.gradient_effects.gradients import load_builtin


async def add_strip(hass: HomeAssistant, source: str, reverse: bool = False) -> str:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    if result["type"] is FlowResultType.MENU:  # no library yet: menu first
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "strip"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"source": source})
    assert result["step_id"] == "settings"
    assert result["description_placeholders"]["backend"].startswith("Hue")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"reverse": reverse, "mqtt_topic": "zigbee2mqtt/Headboard"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["scene_select"].endswith("_gradient_scene")
    await hass.async_block_till_done()
    return f"{source}_2"


async def test_effect_list_includes_native(hass: HomeAssistant, hue_source):
    light, _ = hue_source
    wrapper = await add_strip(hass, light)
    effects = hass.states.get(wrapper).attributes["effect_list"]
    assert "Candle" in effects and "Fireplace" in effects
    assert "Stop Hue Effect" not in effects and "None" not in effects


async def test_scene_recall_uses_select(hass: HomeAssistant, hue_source):
    light, select = hue_source
    wrapper = await add_strip(hass, light)
    select_calls = async_mock_service(hass, "select", "select_option")
    mqtt_calls = async_mock_service(hass, "mqtt", "publish")

    await hass.services.async_call(
        "light", "turn_on", {"entity_id": wrapper, "effect": "Vapor Wave", "brightness": 150}, blocking=True
    )
    assert [c.data["option"] for c in select_calls] == ["vapor_wave"]
    assert select_calls[0].data["entity_id"] == select
    assert not mqtt_calls
    # HA only reports effect while on; the real strip turns on, the mock needs a nudge.
    hass.states.async_set(light, "on", {**hass.states.get(light).attributes, "color_mode": "xy",
                                        "xy_color": (0.2, 0.1), "brightness": 150})
    await hass.async_block_till_done()
    assert hass.states.get(wrapper).attributes["effect"] == "Vapor Wave"


async def test_reverse_sends_gradient_over_mqtt(hass: HomeAssistant, hue_source):
    light, _ = hue_source
    wrapper = await add_strip(hass, light, reverse=True)
    select_calls = async_mock_service(hass, "select", "select_option")
    mqtt_calls = async_mock_service(hass, "mqtt", "publish")

    await hass.services.async_call(
        "light", "turn_on", {"entity_id": wrapper, "effect": "Vapor Wave", "brightness": 150}, blocking=True
    )
    assert not select_calls
    assert mqtt_calls[0].data["topic"] == "zigbee2mqtt/Headboard/set"
    payload = json.loads(mqtt_calls[0].data["payload"])
    assert payload["brightness"] == 150 and payload["state"] == "ON"
    # z2m flips the list for Hue gradient lights, so "reversed" is sent in scene order.
    assert payload["gradient"] == vapor_wave().z2m_hex()


async def test_custom_gradient_sent_pre_flipped(hass: HomeAssistant, hue_source):
    """A custom gradient played forwards is sent back-to-front, so it lands
    first-colour-first after z2m's own flip."""
    data = await async_get_data(hass)
    await data.async_save_custom("Duo", [[255, 0, 0], [0, 0, 255]])
    light, _ = hue_source
    wrapper = await add_strip(hass, light)
    mqtt_calls = async_mock_service(hass, "mqtt", "publish")

    await hass.services.async_call("light", "turn_on", {"entity_id": wrapper, "effect": "Duo"}, blocking=True)
    sent = json.loads(mqtt_calls[0].data["payload"])["gradient"]
    duo = data.catalogue.by_label("Duo")
    assert sent == list(reversed(duo.z2m_hex()))
    assert sent[0].startswith("#") and sent[-1] != sent[0]


def vapor_wave():
    return next(g for g in load_builtin() if g.hue_scene == "vapor_wave")


async def test_unsupported_light_rejected(hass: HomeAssistant):
    hass.states.async_set("light.plain", "on", {})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "strip"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"source": "light.plain"})
    assert result["errors"] == {"source": "not_found"}
