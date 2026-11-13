"""Colour conversions shared by the Hue and WLED backends.

Pure functions, no Home Assistant imports, so they can be unit tested directly.

Two RGB flavours are in play:

* sRGB (gamma encoded) is what WLED expects: its output stage applies its own gamma
  correction, so palettes are written as normal display colours.
* "z2m RGB" is what Zigbee2MQTT's ``gradient`` property expects: z2m converts hex
  straight to CIE xy with the Philips Wide RGB D65 matrix and no gamma step. Sending
  colours in that form makes the strip land on exactly the xy we intended.
"""

from __future__ import annotations

from collections.abc import Sequence

# Philips Wide RGB D65 (as used by zigbee-herdsman-converters' ColorRGB / ColorXY).
_WIDE_TO_XYZ = (
    (0.664511, 0.154324, 0.162028),
    (0.283881, 0.668433, 0.047685),
    (0.000088, 0.07231, 0.986039),
)
_XYZ_TO_WIDE = (
    (1.656492, -0.354851, -0.255038),
    (-0.707196, 1.655397, 0.036152),
    (0.051713, -0.121364, 1.01153),
)
# Standard sRGB (D65) primaries, for colours the user picks in the UI.
_SRGB_TO_XYZ = (
    (0.4124564, 0.3575761, 0.1804375),
    (0.2126729, 0.7151522, 0.0721750),
    (0.0193339, 0.1191920, 0.9503041),
)

RGB = tuple[int, int, int]
XY = tuple[float, float]


def _mul(m: Sequence[Sequence[float]], v: Sequence[float]) -> tuple[float, float, float]:
    return tuple(m[i][0] * v[0] + m[i][1] * v[1] + m[i][2] * v[2] for i in range(3))  # type: ignore[return-value]


def _srgb_encode(v: float) -> float:
    return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055


def _srgb_decode(v: float) -> float:
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _xy_to_wide_linear(x: float, y: float) -> tuple[float, float, float]:
    """xy at Y=1 -> linear Wide RGB, negatives clipped, brightest channel scaled to 1."""
    if y <= 0:
        return (0.0, 0.0, 0.0)
    xyz = ((x / y), 1.0, (1.0 - x - y) / y)
    rgb = [max(c, 0.0) for c in _mul(_XYZ_TO_WIDE, xyz)]
    peak = max(rgb) or 1.0
    return (rgb[0] / peak, rgb[1] / peak, rgb[2] / peak)


def xy_to_srgb(x: float, y: float) -> RGB:
    """CIE xy -> 8-bit sRGB at full intensity (for WLED palettes)."""
    return tuple(round(_srgb_encode(c) * 255) for c in _xy_to_wide_linear(x, y))  # type: ignore[return-value]


def xy_to_z2m_rgb(x: float, y: float) -> RGB:
    """CIE xy -> the RGB Zigbee2MQTT will convert back to (approximately) the same xy."""
    return tuple(round(c * 255) for c in _xy_to_wide_linear(x, y))  # type: ignore[return-value]


def z2m_rgb_to_xy(rgb: RGB) -> XY:
    """Zigbee2MQTT's own hex -> xy conversion (ColorRGB.toXY), for round-trip checks."""
    X, Y, Z = _mul(_WIDE_TO_XYZ, [c / 255 for c in rgb])
    total = X + Y + Z
    return (0.0, 0.0) if total == 0 else (X / total, Y / total)


def srgb_to_xy(rgb: RGB) -> XY:
    """8-bit sRGB (a colour picked in the UI) -> CIE xy."""
    X, Y, Z = _mul(_SRGB_TO_XYZ, [_srgb_decode(c / 255) for c in rgb])
    total = X + Y + Z
    return (0.3127, 0.329) if total == 0 else (X / total, Y / total)


def to_hex(rgb: RGB) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def palette_stops(count: int) -> list[int]:
    """Evenly spaced WLED palette positions 0..255 (matches Hue's linear gradient)."""
    if count <= 1:
        return [0]
    return [round(i * 255 / (count - 1)) for i in range(count)]


def wled_palette(colours: Sequence[RGB]) -> list[int]:
    """Flat WLED custom-palette array: [pos, r, g, b, pos, r, g, b, ...]."""
    flat: list[int] = []
    for pos, (r, g, b) in zip(palette_stops(len(colours)), colours, strict=True):
        flat += [pos, r, g, b]
    return flat
