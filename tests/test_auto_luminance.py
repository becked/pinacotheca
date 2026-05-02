"""Tests for the auto-luminance dark-diffuse compensation helper."""

from __future__ import annotations

import numpy as np
from PIL import Image

from pinacotheca.prefab import apply_auto_luminance_compensation


def _solid(color: tuple[int, int, int, int]) -> Image.Image:
    """Build a 4×4 RGBA image filled with the given (R, G, B, A)."""
    arr = np.full((4, 4, 4), color, dtype=np.uint8)
    return Image.fromarray(arr, mode="RGBA")


def _visible_luminance(img: Image.Image) -> float:
    """Mean BT.601 luminance over alpha > 128 pixels — mirrors the helper."""
    arr = np.asarray(img.convert("RGBA"))
    visible = arr[..., :3][arr[..., 3] > 128]
    if visible.size == 0:
        return 0.0
    return float(
        visible[:, 0].mean() * 0.30 + visible[:, 1].mean() * 0.59 + visible[:, 2].mean() * 0.11
    )


def test_yazilikaya_class_dark_diffuse_lifted_to_target() -> None:
    """Yazilikaya's measured RGB (41, 38, 32) → luminance 38 → lift to ~130."""
    yazilikaya_like = _solid((41, 38, 32, 255))
    assert abs(_visible_luminance(yazilikaya_like) - 38) < 1
    out = apply_auto_luminance_compensation(yazilikaya_like)
    assert abs(_visible_luminance(out) - 130) < 2


def test_normal_brightness_passes_through_unchanged() -> None:
    """Library's measured (165, 145, 115) → luminance 148 → unchanged."""
    library_like = _solid((165, 145, 115, 255))
    out = apply_auto_luminance_compensation(library_like)
    assert np.array_equal(np.asarray(out), np.asarray(library_like))


def test_just_below_threshold_still_lifted() -> None:
    """Threshold gate is a hard cutoff at 70 — a tile at 65 is lifted."""
    near_threshold = _solid((68, 65, 60, 255))
    assert 60 < _visible_luminance(near_threshold) < 70
    out = apply_auto_luminance_compensation(near_threshold)
    assert _visible_luminance(out) > 120


def test_fully_transparent_image_returns_unchanged() -> None:
    """No visible pixels → no luminance → no-op."""
    transparent = _solid((100, 100, 100, 0))
    out = apply_auto_luminance_compensation(transparent)
    assert np.array_equal(np.asarray(out), np.asarray(transparent))


def test_zero_luminance_image_returns_unchanged() -> None:
    """Pure-black diffuse must short-circuit, not divide by zero."""
    pure_black = _solid((0, 0, 0, 255))
    out = apply_auto_luminance_compensation(pure_black)
    assert np.array_equal(np.asarray(out), np.asarray(pure_black))


def test_luminance_measurement_ignores_transparent_pixels() -> None:
    """Transparent-bright pixels must not pull the measured luminance up
    past the threshold; only opaque pixels count."""
    arr = np.zeros((2, 2, 4), dtype=np.uint8)
    arr[0, :] = (255, 255, 255, 0)
    arr[1, :] = (40, 40, 40, 255)
    img = Image.fromarray(arr, mode="RGBA")
    out_arr = np.asarray(apply_auto_luminance_compensation(img))
    assert out_arr[1, 0, 0] > 100  # was 40, lifted
    assert out_arr[0, 0, 3] == 0  # alpha preserved


def test_alpha_channel_preserved_on_lift() -> None:
    """Compensation must touch RGB only; alpha is bit-exact."""
    dark_translucent = _solid((40, 40, 40, 200))
    out_arr = np.asarray(apply_auto_luminance_compensation(dark_translucent))
    assert (out_arr[..., 3] == 200).all()


def test_bright_pixels_clamp_at_255() -> None:
    """When the mean is dark enough to trigger a 4×+ scale, individual
    bright pixels must clip at 255 rather than wrap."""
    arr = np.full((4, 4, 4), 30, dtype=np.uint8)
    arr[..., 3] = 255
    arr[0, 0, :3] = 200
    out_arr = np.asarray(apply_auto_luminance_compensation(Image.fromarray(arr, mode="RGBA")))
    assert tuple(out_arr[0, 0, :3]) == (255, 255, 255)
