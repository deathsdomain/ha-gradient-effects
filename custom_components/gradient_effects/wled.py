"""WLED controller client: palette cache + static gradient display.

Talks to WLED's JSON API directly (the WLED integration has no palette upload or
`rev`/effect-option support). Only needs an aiohttp session, so it can be tested
without Home Assistant.

Facts this relies on (verified on WLED 16.0.1 / ESP32):
* upload: POST /upload, multipart field "data", filename "/paletteN.json"; any upload
  whose name contains "palette" reloads custom palettes immediately
* delete: GET /edit?func=delete&path=/name (palettes reload only on the next upload
  or reboot, so slots are overwritten rather than deleted)
* file N is palette ID 200 - N; info.cpalmax gives the slot count
* static palette across a 1D segment: fx 65 (Palette), sx 0, ix 128, c1 0,
  o1/o2/o3 off
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any

import aiohttp

from .palette_cache import CacheFullError, PaletteCache, Slot, palette_id_to_slot, slot_to_palette_id

_LOGGER = logging.getLogger(__name__)

MANIFEST_FILE = "gradient-effects.json"
FX_PALETTE = 65
FX_SOLID = 0
# Pre-16 firmware: custom palettes count down from 255 and there are at most 10.
LEGACY_BASE_ID = 255
LEGACY_CAPACITY = 10
TIMEOUT = aiohttp.ClientTimeout(total=10)


def palette_content_hash(palette: list[Any]) -> str:
    blob = json.dumps(palette, separators=(",", ":")).encode()
    return hashlib.sha1(blob).hexdigest()[:12]


class WledError(Exception):
    """Talking to the controller failed."""


class WledController:
    """One physical WLED controller, shared by every strip (segment) on it."""

    def __init__(self, session: aiohttp.ClientSession, host: str) -> None:
        self._session = session
        self.host = host
        self._lock = asyncio.Lock()
        self._cache: PaletteCache | None = None
        self._legacy = False

    @property
    def _base(self) -> str:
        return f"http://{self.host}"

    # --- raw API -----------------------------------------------------------------

    async def _get_json(self, path: str) -> Any:
        try:
            async with self._session.get(self._base + path, timeout=TIMEOUT) as resp:
                if resp.status == 404:
                    return None
                resp.raise_for_status()
                return json.loads(await resp.text())
        except (aiohttp.ClientError, TimeoutError, json.JSONDecodeError) as err:
            raise WledError(f"GET {path} failed: {err}") from err

    async def _upload(self, name: str, payload: dict[str, Any]) -> None:
        form = aiohttp.FormData()
        form.add_field(
            "data",
            json.dumps(payload, separators=(",", ":")).encode(),
            filename=f"/{name}",
            content_type="application/json",
        )
        try:
            async with self._session.post(self._base + "/upload", data=form, timeout=TIMEOUT) as resp:
                resp.raise_for_status()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise WledError(f"upload {name} failed: {err}") from err

    async def set_state(self, payload: dict[str, Any]) -> None:
        try:
            async with self._session.post(self._base + "/json/state", json=payload, timeout=TIMEOUT) as resp:
                resp.raise_for_status()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise WledError(f"set state failed: {err}") from err

    async def info(self) -> dict[str, Any]:
        data = await self._get_json("/json/info")
        if not isinstance(data, dict):
            raise WledError("no /json/info")
        return data

    # --- palette cache -----------------------------------------------------------

    def _slot_to_id(self, slot: int) -> int:
        return (LEGACY_BASE_ID - slot) if self._legacy else slot_to_palette_id(slot)

    def _id_to_slot(self, palette_id: int) -> int:
        return (LEGACY_BASE_ID - palette_id) if self._legacy else palette_id_to_slot(palette_id)

    async def _load_cache(self, known_hashes: set[str]) -> PaletteCache:
        info = await self.info()
        if "cpalmax" in info:
            capacity = int(info["cpalmax"])
        else:
            self._legacy = True
            capacity = LEGACY_CAPACITY

        manifest = await self._get_json(f"/{MANIFEST_FILE}")
        adopted = not (isinstance(manifest, dict) and manifest.get("host_capacity") == capacity)
        if adopted:
            cache = await self._adopt_existing(capacity, known_hashes)
        else:
            cache = PaletteCache.from_manifest(capacity, manifest)

        cache.set_pinned(await self._preset_slots(capacity))
        self._cache = cache
        if adopted:
            # Write the map straight away: adopting means fetching every palette file,
            # which shouldn't be repeated after each Home Assistant restart.
            await self._save_manifest()
        return cache

    async def _ensure_loaded(self, known_hashes: set[str]) -> PaletteCache:
        """Caller must hold ``self._lock``."""
        if self._cache is None:
            await self._load_cache(known_hashes)
        assert self._cache is not None
        return self._cache

    async def prepare(self, known_hashes: set[str]) -> None:
        """Load (or adopt) the slot map ahead of the first effect change."""
        async with self._lock:
            await self._ensure_loaded(known_hashes)

    async def _adopt_existing(self, capacity: int, known_hashes: set[str]) -> PaletteCache:
        """First contact (no manifest): hash palette files already on the controller.
        Ones we recognise become cache entries; anything else is left alone (pinned)."""
        cache = PaletteCache(capacity=capacity)
        files = await self._get_json("/edit?list=/") or []
        names = {f.get("name") for f in files if isinstance(f, dict)}
        for slot in range(capacity):
            name = f"palette{slot}.json"
            if name not in names:
                continue
            data = await self._get_json(f"/{name}")
            palette = data.get("palette") if isinstance(data, dict) else None
            content = palette_content_hash(palette) if isinstance(palette, list) else ""
            if content in known_hashes:
                cache.slots[slot] = Slot(content=content)
            else:
                cache.slots[slot] = Slot(content="", pinned=True)
        _LOGGER.debug("%s: adopted %d palette slots", self.host, len(cache.slots))
        return cache

    async def _preset_slots(self, capacity: int) -> set[int]:
        """Slots referenced by WLED presets must never be overwritten."""
        presets = await self._get_json("/presets.json") or {}
        slots: set[int] = set()
        for preset in presets.values() if isinstance(presets, dict) else []:
            if not isinstance(preset, dict):
                continue
            for seg in preset.get("seg", []) or []:
                pal = seg.get("pal") if isinstance(seg, dict) else None
                if isinstance(pal, int):
                    slot = self._id_to_slot(pal)
                    if 0 <= slot < capacity:
                        slots.add(slot)
        return slots

    async def _save_manifest(self) -> None:
        assert self._cache is not None
        manifest = self._cache.to_manifest()
        manifest["host_capacity"] = self._cache.capacity
        await self._upload(MANIFEST_FILE, manifest)

    async def ensure_palette(self, palette: list[int], known_hashes: set[str]) -> int:
        """Make sure ``palette`` is on the controller; return its palette ID."""
        content = palette_content_hash(palette)
        async with self._lock:
            cache = await self._ensure_loaded(known_hashes)
            try:
                slot, needs_upload = cache.allocate(content)
            except CacheFullError as err:
                raise WledError(str(err)) from err
            if needs_upload:
                _LOGGER.debug("%s: uploading palette to slot %d", self.host, slot)
                await self._upload(f"palette{slot}.json", {"palette": palette})
                # Only persist when the slot map changed: hits just bump in-memory LRU
                # order, so every effect change doesn't cost a flash write.
                await self._save_manifest()
            return self._slot_to_id(slot)

    def invalidate(self) -> None:
        """Re-read the controller's palettes and presets on next use."""
        self._cache = None

    # --- display -----------------------------------------------------------------

    async def show_palette(
        self,
        segment: int,
        palette_id: int,
        *,
        reverse: bool,
        brightness: int | None,
    ) -> None:
        payload: dict[str, Any] = {
            "on": True,
            "seg": [{
                "id": segment,
                "fx": FX_PALETTE,
                "pal": palette_id,
                "sx": 0,
                "ix": 128,
                "c1": 0,
                "o1": False,
                "o2": False,
                "o3": False,
                "rev": reverse,
            }],
        }
        if brightness is not None:
            payload["bri"] = brightness
        await self.set_state(payload)
