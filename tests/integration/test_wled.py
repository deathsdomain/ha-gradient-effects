"""WLED strip: config flow, palette cache upload, and scene-style turn_on routing."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.gradient_effects.const import DOMAIN
from custom_components.gradient_effects.gradients import load_builtin

from .conftest import WLED_HOST

BASE = f"http://{WLED_HOST}"


def mock_controller(
    aioclient_mock: AiohttpClientMocker, presets: dict | None = None, files: dict[str, dict] | None = None
) -> None:
    files = files or {}
    aioclient_mock.get(f"{BASE}/json/info", json={"ver": "16.0.1", "cpalmax": 129, "cpalcount": len(files)})
    aioclient_mock.get(f"{BASE}/gradient-effects.json", status=404)
    aioclient_mock.get(f"{BASE}/edit?list=/", json=[{"name": n, "type": "file", "size": 1} for n in files])
    for name, body in files.items():
        aioclient_mock.get(f"{BASE}/{name}", json=body)
    aioclient_mock.get(f"{BASE}/presets.json", json=presets or {})
    aioclient_mock.post(f"{BASE}/upload", text="File Uploaded!")
    aioclient_mock.post(f"{BASE}/json/state", json={"success": True})


def calls(aioclient_mock: AiohttpClientMocker, method: str, path: str) -> list:
    return [c for c in aioclient_mock.mock_calls if c[0] == method and str(c[1]).startswith(BASE + path)]


async def add_strip(hass: HomeAssistant, source: str, reverse: bool = False) -> str:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "strip"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"source": source})
    assert result["step_id"] == "settings"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"reverse": reverse, "segment": 0}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["backend"] == "wled"
    assert result["data"]["host"] == WLED_HOST
    await hass.async_block_till_done()
    return f"{source}_2"  # wrapper joins the source's device; HA suffixes the entity id


async def test_effect_list_and_upload(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, wled_source):
    mock_controller(aioclient_mock)
    wrapper = await add_strip(hass, wled_source)

    # Setup warmed the cache in the background and recorded the (empty) slot map once.
    assert len(calls(aioclient_mock, "POST", "/upload")) == 1

    state = hass.states.get(wrapper)
    assert state is not None, hass.states.async_entity_ids("light")
    effects = state.attributes["effect_list"]
    assert effects[0] == "Solid" and "Vapor Wave" in effects and len(effects) == 76

    # Scene-style call: effect + a colour + brightness in one go. The gradient must win.
    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": wrapper, "effect": "Vapor Wave", "brightness": 200, "xy_color": (0.5, 0.4)},
        blocking=True,
    )
    uploads = calls(aioclient_mock, "POST", "/upload")
    assert len(uploads) == 3  # + palette0.json + manifest
    posted = calls(aioclient_mock, "POST", "/json/state")[-1][2]
    seg = posted["seg"][0]
    assert posted["bri"] == 200 and posted["on"] is True
    assert seg["fx"] == 65 and seg["pal"] == 200 and seg["rev"] is False and seg["o3"] is False
    assert hass.states.get(wrapper).attributes["effect"] == "Vapor Wave"

    # Same gradient again: cache hit, no further uploads.
    await hass.services.async_call("light", "turn_on", {"entity_id": wrapper, "effect": "Vapor Wave"}, blocking=True)
    assert len(calls(aioclient_mock, "POST", "/upload")) == 3


async def test_reverse_and_pinned_presets(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, wled_source):
    # A preset already uses palette ID 200 (slot 0): it must not be overwritten.
    mock_controller(aioclient_mock, presets={"4": {"n": "Mine", "seg": [{"pal": 200}]}})
    wrapper = await add_strip(hass, wled_source, reverse=True)

    await hass.services.async_call("light", "turn_on", {"entity_id": wrapper, "effect": "Smitten"}, blocking=True)
    seg = calls(aioclient_mock, "POST", "/json/state")[-1][2]["seg"][0]
    assert seg["rev"] is True
    assert seg["pal"] == 199  # slot 1, because slot 0 is pinned by the preset


async def test_solid_clears_effect(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, wled_source):
    mock_controller(aioclient_mock)
    wrapper = await add_strip(hass, wled_source)
    await hass.services.async_call("light", "turn_on", {"entity_id": wrapper, "effect": "Blossom"}, blocking=True)
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": wrapper, "rgb_color": (0, 0, 255)}, blocking=True
    )
    assert hass.states.get(wrapper).attributes.get("effect") is None


async def test_adopts_existing_palettes(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, wled_source):
    """Palettes uploaded before the integration (like MasterBedroomTV's 75) are reused,
    and foreign ones are left alone."""
    blossom = next(g for g in load_builtin() if g.hue_scene == "blossom")
    mock_controller(
        aioclient_mock,
        files={
            "palette0.json": {"palette": [0, 1, 2, 3, 255, 4, 5, 6]},  # someone else's
            "palette1.json": {"palette": blossom.wled_palette()},
        },
    )
    wrapper = await add_strip(hass, wled_source)
    assert len(calls(aioclient_mock, "POST", "/upload")) == 1  # manifest only

    await hass.services.async_call("light", "turn_on", {"entity_id": wrapper, "effect": "Blossom"}, blocking=True)
    assert calls(aioclient_mock, "POST", "/json/state")[-1][2]["seg"][0]["pal"] == 199  # slot 1, no upload
    assert len(calls(aioclient_mock, "POST", "/upload")) == 1

    await hass.services.async_call("light", "turn_on", {"entity_id": wrapper, "effect": "Smitten"}, blocking=True)
    assert calls(aioclient_mock, "POST", "/json/state")[-1][2]["seg"][0]["pal"] == 198  # skips foreign slot 0
