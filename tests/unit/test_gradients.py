import pytest

from custom_components.gradient_effects.gradients import (
    Catalogue,
    custom_from_dict,
    load_builtin,
    slugify,
)


@pytest.fixture(scope="module")
def builtin():
    return load_builtin()


def test_builtin_shape(builtin):
    assert len(builtin) == 75
    assert all(len(g.xy) == 5 and len(g.srgb) == 5 for g in builtin)
    assert len({g.label for g in builtin}) == 75


def test_builtin_labels_match_z2m_options(builtin):
    by_scene = {g.hue_scene: g.label for g in builtin}
    assert by_scene["vapor_wave"] == "Vapor Wave"
    assert by_scene["blood moon"] == "Blood Moon"


def test_known_palette(builtin):
    """Smitten is palette14.json on MasterBedroomTV (ID 186)."""
    smitten = next(g for g in builtin if g.hue_scene == "smitten")
    assert smitten.wled_palette()[:4] == [0, 255, 145, 86]


def test_z2m_reverse(builtin):
    g = builtin[0]
    assert g.z2m_hex(reverse=True) == list(reversed(g.z2m_hex()))


def test_custom_validation():
    with pytest.raises(ValueError):
        custom_from_dict({"id": "x", "name": "x", "colours": [[255, 0, 0]]})
    g = custom_from_dict({"id": "sunset", "name": "Sunset", "colours": [[255, 0, 0], [0, 0, 255]]})
    assert g.is_custom and g.key == "custom:sunset" and g.wled_palette() == [0, 255, 0, 0, 255, 0, 0, 255]


def test_catalogue_custom_first_and_clash(builtin):
    custom = custom_from_dict({"id": "lily", "name": "Lily", "colours": [[1, 2, 3], [4, 5, 6]]})
    cat = Catalogue(builtin, [custom])
    assert cat.labels()[0] == "Lily"
    assert cat.by_label("Lily").is_custom
    assert cat.by_label("Lily (Hue)").hue_scene == "lily"
    assert len(set(cat.labels())) == len(cat)


def test_content_hash_stable(builtin):
    assert builtin[0].content_hash() == builtin[0].content_hash()
    assert builtin[0].content_hash() != builtin[1].content_hash()


def test_slugify():
    assert slugify("  Warm Night!! ") == "warm_night"
    assert slugify("***") == "gradient"
