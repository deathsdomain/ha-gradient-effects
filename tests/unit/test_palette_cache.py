import pytest

from custom_components.gradient_effects.palette_cache import (
    CacheFullError,
    PaletteCache,
    palette_id_to_slot,
    slot_to_palette_id,
)


def test_id_mapping():
    assert slot_to_palette_id(0) == 200
    assert slot_to_palette_id(74) == 126
    assert palette_id_to_slot(186) == 14


def test_hit_and_miss():
    cache = PaletteCache(capacity=3)
    assert cache.allocate("a") == (0, True)
    assert cache.allocate("b") == (1, True)
    assert cache.allocate("a") == (0, False)


def test_lru_eviction():
    cache = PaletteCache(capacity=2)
    cache.allocate("a")
    cache.allocate("b")
    cache.allocate("a")  # b is now least recently used
    assert cache.allocate("c") == (1, True)
    assert cache.find("b") is None
    assert cache.find("a") == 0


def test_pinned_slots_survive():
    cache = PaletteCache(capacity=2)
    cache.allocate("a")
    cache.allocate("b")
    cache.set_pinned({0})
    cache.allocate("b")  # make a the LRU, but it's pinned
    assert cache.allocate("c") == (1, True)
    assert cache.find("a") == 0


def test_all_pinned_raises():
    cache = PaletteCache(capacity=1)
    cache.allocate("a")
    cache.set_pinned({0})
    with pytest.raises(CacheFullError):
        cache.allocate("b")


def test_foreign_slots_stay_pinned():
    cache = PaletteCache(capacity=2)
    cache.set_pinned({1})  # preset points at a slot we never wrote
    assert cache.slots[1].pinned and cache.slots[1].content == ""
    cache.set_pinned(set())  # preset removed, but the slot is still foreign
    assert cache.slots[1].pinned


def test_manifest_round_trip():
    cache = PaletteCache(capacity=4)
    for content in ("a", "b", "c"):
        cache.allocate(content)
    cache.allocate("a")
    restored = PaletteCache.from_manifest(4, cache.to_manifest())
    assert restored.find("a") == 0
    assert restored.allocate("d") == (3, True)  # free slot first
    assert restored.allocate("e")[0] == 1  # then LRU (b)


def test_manifest_version_mismatch_starts_empty():
    assert not PaletteCache.from_manifest(4, {"version": 99, "slots": {"0": {"content": "a"}}}).slots
