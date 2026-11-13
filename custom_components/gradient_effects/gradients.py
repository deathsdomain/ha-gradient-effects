"""Gradient catalogue: the built-in Hue scenes plus user-defined gradients (pure logic)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .colour import RGB, XY, srgb_to_xy, to_hex, wled_palette, xy_to_srgb, xy_to_z2m_rgb

BUILTIN_PATH = Path(__file__).parent / "data" / "gradients.json"

MIN_COLOURS = 2
MAX_COLOURS = 9  # Zigbee2MQTT's `gradient` limit


@dataclass(frozen=True)
class Gradient:
    key: str  # stable id: "hue:<scene>" or "custom:<slug>"
    label: str  # what appears in the effect list
    xy: tuple[XY, ...]
    srgb: tuple[RGB, ...]
    hue_scene: str | None = None  # Z2M gradient_scene option, built-ins only

    @property
    def is_custom(self) -> bool:
        return self.hue_scene is None

    def wled_palette(self) -> list[int]:
        return wled_palette(self.srgb)

    def content_hash(self) -> str:
        """Identifies the palette content on a WLED controller."""
        blob = json.dumps(self.wled_palette(), separators=(",", ":")).encode()
        return hashlib.sha1(blob).hexdigest()[:12]

    def z2m_hex(self, reverse: bool = False) -> list[str]:
        colours = [to_hex(xy_to_z2m_rgb(x, y)) for x, y in self.xy]
        return colours[::-1] if reverse else colours


def load_builtin(path: Path = BUILTIN_PATH) -> list[Gradient]:
    data = json.loads(path.read_text())
    return [
        Gradient(
            key=f"hue:{entry['scene']}",
            label=entry["label"],
            xy=tuple((float(x), float(y)) for x, y in entry["xy"]),
            srgb=tuple(tuple(c) for c in entry["srgb"]),  # type: ignore[misc]
            hue_scene=entry["scene"],
        )
        for entry in data["gradients"]
    ]


def slugify(name: str) -> str:
    out = "".join(ch.lower() if ch.isalnum() else "_" for ch in name.strip())
    return "_".join(part for part in out.split("_") if part) or "gradient"


def custom_from_dict(entry: dict[str, Any]) -> Gradient:
    colours: list[RGB] = [tuple(int(v) for v in c) for c in entry["colours"]]  # type: ignore[misc]
    if not MIN_COLOURS <= len(colours) <= MAX_COLOURS:
        raise ValueError(f"a gradient needs {MIN_COLOURS}-{MAX_COLOURS} colours")
    return Gradient(
        key=f"custom:{entry['id']}",
        label=entry["name"],
        xy=tuple(srgb_to_xy(c) for c in colours),
        srgb=tuple(colours),
    )


class Catalogue:
    """Ordered lookup by key and by effect label (custom gradients listed first)."""

    def __init__(self, builtin: Iterable[Gradient], custom: Iterable[Gradient] = ()) -> None:
        self._items: list[Gradient] = []
        seen: set[str] = set()
        for gradient in [*custom, *builtin]:
            label = gradient.label
            # Custom names win; a clashing built-in gets a suffix so labels stay unique.
            if label in seen:
                label = f"{label} (Hue)"
                gradient = Gradient(gradient.key, label, gradient.xy, gradient.srgb, gradient.hue_scene)
            seen.add(label)
            self._items.append(gradient)
        self._by_label = {g.label: g for g in self._items}
        self._by_key = {g.key: g for g in self._items}

    def __iter__(self):
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def labels(self) -> list[str]:
        return [g.label for g in self._items]

    def by_label(self, label: str) -> Gradient | None:
        return self._by_label.get(label)

    def by_key(self, key: str) -> Gradient | None:
        return self._by_key.get(key)


def builtin_entry_from_scene(scene: str, xy: list[XY]) -> dict[str, Any]:
    """Shape of one data/gradients.json entry (used by tools/build_gradients.py)."""
    # Round first and convert from the rounded values, so the stored xy and sRGB agree
    # (and match palettes already uploaded by the original decoder).
    rounded = [(round(x, 4), round(y, 4)) for x, y in xy]
    return {
        "scene": scene,
        "label": scene.replace("_", " ").title(),
        "xy": [list(p) for p in rounded],
        "srgb": [list(xy_to_srgb(x, y)) for x, y in rounded],
    }
