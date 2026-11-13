"""Render the integration's brand icon: a wavy LED strip in the Vapor Wave gradient.

Writes custom_components/gradient_effects/brand/icon.png (256 px) and icon@2x.png
(512 px): square, transparent, trimmed — per the Home Assistant brands guidelines.

Usage: uv run --no-project --with pillow python tools/make_icon.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "gradient_effects"
OUT = COMPONENT / "brand"

SS = 2048  # supersampled canvas
SCENE = "vapor_wave"
LEDS = 7


def gradient_colours() -> list[tuple[int, int, int]]:
    data = json.loads((COMPONENT / "data" / "gradients.json").read_text())
    entry = next(g for g in data["gradients"] if g["scene"] == SCENE)
    return [tuple(c) for c in entry["srgb"]]


def sample(colours, t: float) -> tuple[int, int, int]:
    """Linear interpolation across evenly spaced stops, like a WLED palette."""
    pos = t * (len(colours) - 1)
    i = min(int(pos), len(colours) - 2)
    f = pos - i
    a, b = colours[i], colours[i + 1]
    return tuple(round(a[k] + (b[k] - a[k]) * f) for k in range(3))


def curve(t: float) -> tuple[float, float]:
    pad = SS * 0.16
    x = pad + t * (SS - 2 * pad)
    y = SS / 2 - SS * 0.17 * math.sin(2 * math.pi * t)
    return x, y


def render() -> Image.Image:
    colours = gradient_colours()
    img = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    radius = SS * 0.105

    # Soft glow underneath, so the strip reads on light and dark backgrounds alike.
    glow = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    steps = 900
    for i in range(steps + 1):
        t = i / steps
        x, y = curve(t)
        r, g, b = sample(colours, t)
        gd.ellipse((x - radius * 1.25, y - radius * 1.25, x + radius * 1.25, y + radius * 1.25), fill=(r, g, b, 70))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(SS * 0.03)))

    # The strip body: overlapping discs along the curve give a smooth tube with round ends.
    d = ImageDraw.Draw(img)
    for i in range(steps + 1):
        t = i / steps
        x, y = curve(t)
        d.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(*sample(colours, t), 255))

    # LEDs, evenly spaced along the strip (by arc length, not by x).
    led = radius * 0.36
    ts = [i / steps for i in range(steps + 1)]
    pts = [curve(t) for t in ts]
    lengths = [0.0]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
        lengths.append(lengths[-1] + math.hypot(x1 - x0, y1 - y0))
    total = lengths[-1]
    for i in range(LEDS):
        target = total * (0.06 + 0.88 * i / (LEDS - 1))
        j = next(k for k, s in enumerate(lengths) if s >= target)
        x, y = pts[j]
        d.ellipse((x - led, y - led, x + led, y + led), fill=(255, 255, 255, 235))
    return img


def trim_square(img: Image.Image, margin: float = 0.02) -> Image.Image:
    left, top, right, bottom = img.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    side = max(right - left, bottom - top)
    side += int(side * margin * 2)
    cx, cy = (left + right) / 2, (top + bottom) / 2
    box = (int(cx - side / 2), int(cy - side / 2), int(cx - side / 2) + side, int(cy - side / 2) + side)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(img.crop(box), (0, 0))
    return square


def main() -> None:
    OUT.mkdir(exist_ok=True)
    icon = trim_square(render())
    for size, name in ((256, "icon.png"), (512, "icon@2x.png")):
        icon.resize((size, size), Image.LANCZOS).save(OUT / name, optimize=True)
        print(f"wrote {(OUT / name).relative_to(ROOT)} ({size}x{size})")


if __name__ == "__main__":
    main()
