"""Slot bookkeeping for WLED custom palettes (pure logic, no I/O).

WLED stores custom palettes as /paletteN.json and exposes file N as palette ID
``200 - N`` (checked on WLED 16.0.1: IDs follow the file index; gaps load as grey
placeholders). A controller has ``capacity`` slots (``info.cpalmax``).

This class decides which slot a gradient lives in:

* hit: the gradient's content hash is already in a slot -> reuse it
* miss: take the lowest free slot, else evict the least recently used unpinned slot
* pinned slots (referenced by WLED presets, or palettes we didn't write) are never
  evicted

The map is serialised to a manifest file on the controller so it survives Home
Assistant restarts and reinstalls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

FIRST_CUSTOM_PALETTE_ID = 200
MANIFEST_VERSION = 1


def slot_to_palette_id(slot: int) -> int:
    return FIRST_CUSTOM_PALETTE_ID - slot


def palette_id_to_slot(palette_id: int) -> int:
    return FIRST_CUSTOM_PALETTE_ID - palette_id


class CacheFullError(Exception):
    """Every slot is pinned, so nothing can be evicted."""


@dataclass
class Slot:
    content: str  # content hash of the palette in this slot ("" = unknown/foreign)
    last_used: int = 0
    pinned: bool = False


@dataclass
class PaletteCache:
    capacity: int
    slots: dict[int, Slot] = field(default_factory=dict)
    _clock: int = 0

    # --- queries -----------------------------------------------------------------

    def find(self, content: str) -> int | None:
        for index, slot in self.slots.items():
            if slot.content == content:
                return index
        return None

    def pinned_slots(self) -> set[int]:
        return {i for i, s in self.slots.items() if s.pinned}

    # --- updates -----------------------------------------------------------------

    def touch(self, index: int) -> None:
        self._clock += 1
        self.slots[index].last_used = self._clock

    def allocate(self, content: str) -> tuple[int, bool]:
        """Return (slot, needs_upload) for ``content``, updating LRU order."""
        hit = self.find(content)
        if hit is not None:
            self.touch(hit)
            return hit, False

        index = self._free_slot()
        if index is None:
            index = self._eviction_candidate()
        self.slots[index] = Slot(content=content)
        self.touch(index)
        return index, True

    def set_pinned(self, indices: set[int]) -> None:
        """Pin exactly ``indices`` (e.g. slots referenced by presets); unpin the rest
        unless they hold foreign content."""
        for index, slot in self.slots.items():
            slot.pinned = index in indices or slot.content == ""
        for index in indices:
            if index not in self.slots and 0 <= index < self.capacity:
                self.slots[index] = Slot(content="", pinned=True)

    def forget(self, content: str) -> None:
        """Drop a hash (e.g. a custom gradient that was edited) so its slot is reusable."""
        for slot in self.slots.values():
            if slot.content == content and not slot.pinned:
                slot.last_used = 0

    # --- internals ---------------------------------------------------------------

    def _free_slot(self) -> int | None:
        for index in range(self.capacity):
            if index not in self.slots:
                return index
        return None

    def _eviction_candidate(self) -> int:
        candidates = [(s.last_used, i) for i, s in self.slots.items() if not s.pinned]
        if not candidates:
            raise CacheFullError(f"all {self.capacity} palette slots are pinned")
        return min(candidates)[1]

    # --- persistence -------------------------------------------------------------

    def to_manifest(self) -> dict[str, Any]:
        return {
            "version": MANIFEST_VERSION,
            "clock": self._clock,
            "slots": {
                str(i): {"content": s.content, "last_used": s.last_used}
                for i, s in sorted(self.slots.items())
                if s.content
            },
        }

    @classmethod
    def from_manifest(cls, capacity: int, data: dict[str, Any]) -> PaletteCache:
        cache = cls(capacity=capacity)
        if data.get("version") != MANIFEST_VERSION:
            return cache
        cache._clock = int(data.get("clock", 0))
        for key, entry in data.get("slots", {}).items():
            index = int(key)
            if 0 <= index < capacity:
                cache.slots[index] = Slot(
                    content=str(entry.get("content", "")),
                    last_used=int(entry.get("last_used", 0)),
                )
        return cache
