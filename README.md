# Gradient Effects

A Home Assistant integration that gives **Philips Hue gradient strips** (via Zigbee2MQTT)
and **WLED strips** one shared effect list of gradients. Pick "Vapor Wave" on either and
you get the same gradient — on a Hue Play strip or a 300-LED WLED run.

- **75 Hue gradient scenes** built in, decoded from Zigbee2MQTT's own scene table
- **Custom gradients** — 2 to 9 colours, defined in the UI, available on every strip
- **Reverse per strip**, for strips mounted the other way round
- **Scene-safe**: effect, colour and brightness are applied in one call, so HA scenes
  restore exactly what you saved
- **WLED palette cache**: palettes are uploaded on demand and recycled least-recently-used,
  so even 10-slot controllers can show the whole catalogue

## How it works

Each strip you add gets a wrapper light on the same device as the original. Its effect
list is: **Solid**, your custom gradients, the 75 Hue scenes, then the device's own effects
(Hue strips keep Candle, Fireplace and so on).

| | Hue gradient strip (Zigbee2MQTT) | WLED |
|---|---|---|
| Built-in scene | Recalled natively via the strip's `gradient_scene` | Custom palette + static *Palette* effect |
| Reversed / custom | Colour points sent via Z2M's `gradient` property | Same palette, segment `rev` flag |
| Solid | Stops any effect, sets the colour | Switches the segment back to *Solid* |

### WLED palette cache

WLED keeps custom palettes as files (`/paletteN.json`, palette ID `200 − N` on WLED 16).
The integration tracks which gradient is in which slot, in a small manifest on the
controller (`/gradient-effects.json`). A gradient already on the controller is shown
instantly; a new one is uploaded into a free slot, or the least recently used one.
Slots referenced by your WLED presets, and palettes the integration didn't write, are
never touched.

## Requirements

- Home Assistant 2026.10 or newer
- Hue gradient strips paired with **Zigbee2MQTT** (they need the `gradient_scene` select)
- WLED 16 recommended (up to 129 palette slots on ESP32). Older firmware and ESP8266
  boards work with 10 slots via the cache.

## Installation

### HACS

1. HACS → ⋮ → **Custom repositories** → add this repository as an **Integration**
2. Install **Gradient Effects**, then restart Home Assistant

### Manual

Copy `custom_components/gradient_effects` into your `config/custom_components/` and restart.

## Setup

1. **Settings → Devices & services → Add integration → Gradient Effects**
2. **Add a strip** → choose the Hue gradient or WLED light. The integration detects which
   it is; set **Reverse gradient** if needed. For Hue strips, check the Zigbee2MQTT topic
   (base topic + the device's Z2M name).
3. Optional: add the integration again and choose **Set up the custom gradient library**.
   Its **Configure** button adds, edits and deletes custom gradients.

Then use the new light in dashboards, scenes and automations, and hide the original.

```yaml
action: light.turn_on
target:
  entity_id: light.master_bedroom_headboard_2
data:
  effect: Tokyo
  brightness_pct: 75
```

## Development

```bash
# pure-logic unit tests (no Home Assistant needed)
uv run --no-project --with pytest python -m pytest tests/unit
# integration tests against a test Home Assistant
uv run --no-project --python 3.14 --with pytest-homeassistant-custom-component python -m pytest tests/integration
# regenerate the built-in gradients from Zigbee2MQTT's source
python3 tools/build_gradients.py
```

## Credits

Icon: `tools/make_icon.py` (the Vapor Wave gradient on a strip).

The built-in gradient scenes are decoded from
[zigbee-herdsman-converters](https://github.com/Koenkk/zigbee-herdsman-converters)
(MIT licence). See [NOTICE](NOTICE).
