"""Fixtures for tests that run inside a real (test) Home Assistant instance."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

WLED_HOST = "10.0.0.5"
WLED_MAC = "aabbccddeeff"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def wled_source(hass: HomeAssistant) -> str:
    """A light that looks like the WLED integration's segment 0 light."""
    wled_entry = MockConfigEntry(domain="wled", data={"host": WLED_HOST}, unique_id=WLED_MAC)
    wled_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=wled_entry.entry_id, identifiers={("wled", WLED_MAC)}, name="TV"
    )
    entity = er.async_get(hass).async_get_or_create(
        "light", "wled", f"{WLED_MAC}_0", config_entry=wled_entry, device_id=device.id, suggested_object_id="tv"
    )
    hass.states.async_set(
        entity.entity_id,
        "on",
        {
            "supported_color_modes": ["rgb"],
            "color_mode": "rgb",
            "brightness": 128,
            "rgb_color": (255, 0, 0),
            "xy_color": (0.701, 0.299),
            "effect": "Solid",
            "effect_list": ["Solid", "Palette"],
        },
    )
    return entity.entity_id


@pytest.fixture
def hue_source(hass: HomeAssistant) -> tuple[str, str]:
    """A Zigbee2MQTT Hue gradient strip: light + gradient_scene select on one device."""
    mqtt_entry = MockConfigEntry(domain="mqtt", data={})
    mqtt_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=mqtt_entry.entry_id,
        identifiers={("mqtt", "zigbee2mqtt_0x0011")},
        name="Headboard",
    )
    ent_reg = er.async_get(hass)
    light = ent_reg.async_get_or_create(
        "light", "mqtt", "0x0011_light_zigbee2mqtt", config_entry=mqtt_entry, device_id=device.id,
        suggested_object_id="headboard",
    )
    select = ent_reg.async_get_or_create(
        "select", "mqtt", "0x0011_gradient_scene_zigbee2mqtt", config_entry=mqtt_entry, device_id=device.id,
        suggested_object_id="headboard_gradient_scene",
    )
    hass.states.async_set(
        light.entity_id,
        "off",
        {
            "supported_color_modes": ["color_temp", "xy"],
            "effect_list": ["candle", "fireplace", "none", "stop_hue_effect"],
        },
    )
    hass.states.async_set(select.entity_id, "unknown", {"options": ["blossom", "vapor_wave", "smitten"]})
    return light.entity_id, select.entity_id
