"""Tests for the neutral team-color pink replacement helper."""

from __future__ import annotations

import numpy as np
from PIL import Image

from pinacotheca.prefab import apply_neutral_team_color


def _img_from_pixels(pixels: list[list[tuple[int, int, int, int]]]) -> Image.Image:
    """Build an RGBA PIL Image from a 2D list of (R, G, B, A) tuples."""
    arr = np.asarray(pixels, dtype=np.uint8)
    return Image.fromarray(arr, mode="RGBA")


def _pixel(img: Image.Image, x: int, y: int) -> tuple[int, int, int, int]:
    return img.getpixel((x, y))  # type: ignore[return-value]


def test_replaces_aksum_style_pink_with_gray() -> None:
    """The hand-painted pink Aksum uses (R~231, G~166, B~164) gets replaced."""
    pink = (231, 166, 164, 255)
    img = _img_from_pixels([[pink]])
    out = apply_neutral_team_color(img)
    assert _pixel(out, 0, 0) == (180, 180, 180, 255)


def test_preserves_red_outside_pink_range() -> None:
    """Pure saturated red (no green/blue) is not pink — must pass through."""
    pure_red = (255, 0, 0, 255)
    img = _img_from_pixels([[pure_red]])
    out = apply_neutral_team_color(img)
    assert _pixel(out, 0, 0) == pure_red


def test_preserves_yellow_and_orange() -> None:
    """Yellow (R=G high) and orange (R high, G mid, B low) read as warm but
    aren't in the pink range and should pass through unchanged."""
    yellow = (255, 220, 80, 255)
    orange = (240, 150, 60, 255)
    img = _img_from_pixels([[yellow, orange]])
    out = apply_neutral_team_color(img)
    assert _pixel(out, 0, 0) == yellow
    assert _pixel(out, 1, 0) == orange


def test_preserves_neutral_grays() -> None:
    """Mid-grays (R=G=B) are not in the pink range — must pass through."""
    gray = (128, 128, 128, 255)
    light = (200, 200, 200, 255)
    img = _img_from_pixels([[gray, light]])
    out = apply_neutral_team_color(img)
    assert _pixel(out, 0, 0) == gray
    assert _pixel(out, 1, 0) == light


def test_replaces_only_pink_pixels_in_mixed_image() -> None:
    """A mixed image: pink, stone, plant green. Only the pink should change."""
    pink = (231, 166, 164, 255)
    stone = (160, 140, 110, 255)  # warm stone — R high but G/B too low for pink range
    leaf = (60, 130, 50, 255)  # green leaf
    pixels = [
        [pink, stone, leaf],
        [stone, pink, pink],
    ]
    img = _img_from_pixels(pixels)
    out = apply_neutral_team_color(img)
    assert _pixel(out, 0, 0) == (180, 180, 180, 255)
    assert _pixel(out, 1, 0) == stone
    assert _pixel(out, 2, 0) == leaf
    assert _pixel(out, 0, 1) == stone
    assert _pixel(out, 1, 1) == (180, 180, 180, 255)
    assert _pixel(out, 2, 1) == (180, 180, 180, 255)


def test_preserves_alpha_channel() -> None:
    """Alpha is preserved on replaced pink pixels, not stomped to 255."""
    pink_with_partial_alpha = (231, 166, 164, 128)
    img = _img_from_pixels([[pink_with_partial_alpha]])
    out = apply_neutral_team_color(img)
    assert _pixel(out, 0, 0) == (180, 180, 180, 128)


def test_does_not_mutate_input() -> None:
    """The helper returns a new image; the input must be unchanged."""
    pink = (231, 166, 164, 255)
    img = _img_from_pixels([[pink]])
    apply_neutral_team_color(img)
    # Input still has pink at (0, 0)
    assert _pixel(img, 0, 0) == pink
