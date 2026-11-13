"""Regenerate custom_components/gradient_effects/data/gradients.json.

Source: zigbee-herdsman-converters src/lib/philips.ts (`export const gradientScenes`),
kept at tools/philips.ts. Refresh it with:

    curl -sSfL -o tools/philips.ts \
      https://raw.githubusercontent.com/Koenkk/zigbee-herdsman-converters/master/src/lib/philips.ts

Then: python3 -I tools/build_gradients.py
"""

from __future__ import annotations

import importlib
import json
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "gradient_effects"

# Import the component's pure modules without running its Home Assistant __init__.
for name, path in (("custom_components", ROOT / "custom_components"),
                   ("custom_components.gradient_effects", COMPONENT)):
    pkg = types.ModuleType(name)
    pkg.__path__ = [str(path)]
    sys.modules[name] = pkg
gradients = importlib.import_module("custom_components.gradient_effects.gradients")

# Same scaling as z2m's decodeScaledGradientToRGB.
MAX_X = 0.7347
MAX_Y = 0.8264


def parse_scene_table(ts_source: str) -> list[tuple[str, str]]:
    start = ts_source.index("export const gradientScenes = {")
    end = ts_source.index("\n};", start)
    return re.findall(r'^\s*"?([^":\n]+?)"?\s*:\s*"([0-9a-fA-F]+)",?\s*$', ts_source[start:end], re.M)


def decode_points(payload: str) -> list[tuple[float, float]]:
    """5001 | 0400 fade | 13 len | <count<<4> | 00 style | 0000 | 6 hex/colour | seg | off"""
    p = payload.lower()
    count = int(p[10:12], 16) >> 4
    style = int(p[12:14], 16)
    if style != 0:
        raise ValueError(f"unexpected gradient style {style}")
    colours = p[18:18 + 6 * count]
    points = []
    for i in range(count):
        c = colours[6 * i:6 * i + 6]
        x = int(c[3] + c[0] + c[1], 16) * MAX_X / 4095
        y = int(c[4] + c[5] + c[2], 16) * MAX_Y / 4095
        points.append((x, y))
    return points


def main() -> None:
    source = (ROOT / "tools" / "philips.ts").read_text()
    entries = [gradients.builtin_entry_from_scene(name, decode_points(payload))
               for name, payload in parse_scene_table(source)]
    out = {"source": "zigbee-herdsman-converters src/lib/philips.ts gradientScenes",
           "gradients": entries}
    target = COMPONENT / "data" / "gradients.json"
    target.write_text(json.dumps(out, indent=1) + "\n")
    print(f"wrote {len(entries)} gradients -> {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
