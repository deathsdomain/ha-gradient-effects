import pytest

from custom_components.gradient_effects.colour import (
    palette_stops,
    srgb_to_xy,
    wled_palette,
    xy_to_srgb,
    xy_to_z2m_rgb,
    z2m_rgb_to_xy,
)


@pytest.mark.parametrize("xy", [(0.1782, 0.1187), (0.5948, 0.3372), (0.3127, 0.329), (0.1588, 0.2646)])
def test_z2m_round_trip(xy):
    """Colours sent via z2m's `gradient` land back on (nearly) the same xy."""
    x, y = z2m_rgb_to_xy(xy_to_z2m_rgb(*xy))
    assert x == pytest.approx(xy[0], abs=0.006)
    assert y == pytest.approx(xy[1], abs=0.006)


def test_full_intensity():
    for xy in [(0.1782, 0.1187), (0.5948, 0.3372), (0.4039, 0.1875)]:
        assert max(xy_to_srgb(*xy)) == 255
        assert max(xy_to_z2m_rgb(*xy)) == 255


def test_known_decode():
    """Blossom's first point, as uploaded to MasterBedroomTV."""
    assert xy_to_srgb(0.2399, 0.2706) == (164, 207, 255)


def test_srgb_white_is_d65():
    x, y = srgb_to_xy((255, 255, 255))
    assert (x, y) == pytest.approx((0.3127, 0.329), abs=0.001)


def test_palette_stops():
    assert palette_stops(5) == [0, 64, 128, 191, 255]
    assert palette_stops(2) == [0, 255]
    assert palette_stops(1) == [0]


def test_wled_palette_layout():
    assert wled_palette([(1, 2, 3), (4, 5, 6)]) == [0, 1, 2, 3, 255, 4, 5, 6]
