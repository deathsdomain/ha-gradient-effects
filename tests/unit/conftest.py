"""Load the component's pure modules without its Home Assistant __init__."""

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

for name, path in (
    ("custom_components", ROOT / "custom_components"),
    ("custom_components.gradient_effects", ROOT / "custom_components" / "gradient_effects"),
):
    if name not in sys.modules:
        pkg = types.ModuleType(name)
        pkg.__path__ = [str(path)]
        sys.modules[name] = pkg
