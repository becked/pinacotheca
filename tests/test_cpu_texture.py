"""Tests for the CPUTexture2D port and inverse-density preprocess.
CI-safe — no game install required; uses synthesized PIL masks."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from pinacotheca.cpu_texture import (
    ColorChannel,
    CPUTexture2D,
    _calculate_inverse_density,
)


def _mask(pixels: list[list[tuple[int, int, int, int]]]) -> Image.Image:
    """Build a PIL RGBA image from a 2D list of (R,G,B,A) uint8 tuples.

    Note PIL's row 0 is at the *top*. CPUTexture2D flips to Unity
    bottom-origin internally, so the bottom row in your input here ends
    up indexed as `_pixels[0]` after construction."""
    arr = np.asarray(pixels, dtype=np.uint8)
    return Image.fromarray(arr, mode="RGBA")


# ============================================================
# _calculate_inverse_density
# ============================================================


def test_all_zero_mask_yields_all_zero_density() -> None:
    """`if (num.EpsilonEquals(0f)) { return new Vector2[pixels.Length]; }`
    — when total == 0, the C# returns a zero-filled array."""
    pixels = np.zeros((4, 4, 4), dtype=np.float64)
    out = _calculate_inverse_density(pixels, 4, 4, ColorChannel.A)
    assert out.shape == (16, 2)
    assert np.all(out == 0.0)


def test_uniform_mask_distributes_one_uv_per_pixel() -> None:
    """Uniform channel → density factor = pixel_count / total = 1.0 (if all
    pixel values are 1.0). Each pixel contributes exactly 1 to the
    accumulator, so each pixel's center UV gets exactly one slot in
    the output array (in row-major order)."""
    pixels = np.zeros((4, 4, 4), dtype=np.float64)
    pixels[..., int(ColorChannel.A)] = 1.0  # all alpha = 1.0
    out = _calculate_inverse_density(pixels, 4, 4, ColorChannel.A)
    assert out.shape == (16, 2)
    expected = []
    for row in range(4):
        for col in range(4):
            expected.append([(col + 0.5) / 4.0, (row + 0.5) / 4.0])
    np.testing.assert_allclose(out, expected, atol=1e-12)


def test_single_bright_pixel_concentrates_all_uvs() -> None:
    """If only one pixel has channel value > 0, every output slot gets
    that pixel's center UV. The accumulator on that one pixel reaches
    `pixel_count = width*height` exactly (density factor = N/total
    cancels with that one pixel's value), and N slots are written
    in the inner-for loop."""
    pixels = np.zeros((4, 4, 4), dtype=np.float64)
    pixels[2, 1, int(ColorChannel.A)] = 1.0  # bright at row 2, col 1
    out = _calculate_inverse_density(pixels, 4, 4, ColorChannel.A)
    expected_uv = ((1 + 0.5) / 4.0, (2 + 0.5) / 4.0)
    for u, v in out:
        assert (u, v) == expected_uv


def test_two_equal_bright_pixels_split_uvs_evenly() -> None:
    """Two pixels each with value 1.0; density factor = 16/2 = 8. Each
    bright pixel adds 8 to the accumulator → 8 slots claimed per
    pixel. So 16 slots total, half pointing at each pixel's center."""
    pixels = np.zeros((4, 4, 4), dtype=np.float64)
    pixels[0, 0, int(ColorChannel.A)] = 1.0
    pixels[3, 3, int(ColorChannel.A)] = 1.0
    out = _calculate_inverse_density(pixels, 4, 4, ColorChannel.A)
    uv_first = (0.5 / 4.0, 0.5 / 4.0)
    uv_second = (3.5 / 4.0, 3.5 / 4.0)
    first_count = sum(1 for u, v in out if (u, v) == uv_first)
    second_count = sum(1 for u, v in out if (u, v) == uv_second)
    assert first_count == 8
    assert second_count == 8


# ============================================================
# CPUTexture2D — full pipeline (constructor + flip + lookups)
# ============================================================


def test_constructor_flips_to_unity_bottom_origin() -> None:
    """PIL row 0 is at the top; we flip so that internal row 0 is at the
    bottom of the texture (Unity convention). Building a mask that's
    bright at PIL-top-left should yield a CPUTexture2D where
    `_pixels[height-1, 0]` is bright (because PIL row 0 ends up at
    the *last* internal row after np.flipud)."""
    pix = [
        [(255, 0, 0, 255), (0, 0, 0, 0)],
        [(0, 0, 0, 0), (0, 0, 0, 0)],
    ]
    tex = CPUTexture2D(_mask(pix))
    assert tex.width == 2
    assert tex.height == 2
    # PIL row 0 (top) became internal row height-1 = 1 after the flip.
    np.testing.assert_allclose(tex._pixels[1, 0], [1.0, 0.0, 0.0, 1.0])
    np.testing.assert_allclose(tex._pixels[0, 0], [0.0, 0.0, 0.0, 0.0])


def test_get_pixel_clamps_out_of_range_uv() -> None:
    pix = [
        [(255, 0, 0, 0), (0, 255, 0, 0)],
        [(0, 0, 255, 0), (0, 0, 0, 255)],
    ]
    tex = CPUTexture2D(_mask(pix))
    # Bottom-left of the Unity-oriented texture (after flip): PIL row 1, col 0
    # = (0, 0, 255, 0) → blue.
    r, g, b, a = tex.get_pixel(0.0, 0.0)
    assert (r, g, b, a) == (0.0, 0.0, 1.0, 0.0)
    # Top-right (Unity): PIL row 0, col 1 = (0, 255, 0, 0) → green.
    r, g, b, a = tex.get_pixel(0.99, 0.99)
    assert (r, g, b, a) == (0.0, 1.0, 0.0, 0.0)


def test_get_inverse_density_uniform_mask_passthrough() -> None:
    """Uniform alpha=255 mask → density array maps each pixel to its own
    center UV. The lookup result for an input UV at a pixel center is
    that center plus a sub-pixel offset of 0 (num3/width and
    num4/height both vanish at the exact center)."""
    pix = [[(0, 0, 0, 255)] * 4 for _ in range(4)]
    tex = CPUTexture2D(_mask(pix))
    # Query at the center of pixel (col=1, row=2 in Unity orientation)
    # → center UV (1.5/4, 2.5/4) = (0.375, 0.625).
    u, v = tex.get_inverse_density(0.375, 0.625, ColorChannel.A)
    assert u == pytest.approx(0.375, abs=1e-12)
    assert v == pytest.approx(0.625, abs=1e-12)


def test_get_inverse_density_clusters_at_bright_pixel() -> None:
    """A single bright pixel acts as an attractor — every input UV maps
    to that pixel's center plus a sub-pixel jitter."""
    # 4x4 mask, bright at Unity (col=1, row=2) → PIL (col=1, row=4-1-2 = 1).
    arr = np.zeros((4, 4, 4), dtype=np.uint8)
    arr[1, 1, 3] = 255  # PIL row 1, col 1, alpha
    tex = CPUTexture2D(Image.fromarray(arr, mode="RGBA"))
    bright_unity_center = ((1 + 0.5) / 4.0, (2 + 0.5) / 4.0)  # (0.375, 0.625)
    # Query at four very different UVs — all should land near the bright pixel.
    for query_u, query_v in [(0.1, 0.1), (0.5, 0.5), (0.9, 0.1), (0.5, 0.9)]:
        u, v = tex.get_inverse_density(query_u, query_v, ColorChannel.A)
        assert abs(u - bright_unity_center[0]) < 0.30
        assert abs(v - bright_unity_center[1]) < 0.30


def test_get_inverse_density_zero_mask_returns_offset_only() -> None:
    """All-zero density array means the lookup returns (0, 0) for every
    pixel; the result is therefore just the sub-pixel offset alone."""
    pix = [[(0, 0, 0, 0)] * 2 for _ in range(2)]
    tex = CPUTexture2D(_mask(pix))
    # Query at u=0.5, v=0.5: floor(0.5*2)=1, sub-pixel offset = 0.5*2 - 1 - 0.5 = -0.5.
    # Result: (0, 0) + (-0.5/2, -0.5/2) = (-0.25, -0.25).
    u, v = tex.get_inverse_density(0.5, 0.5, ColorChannel.A)
    assert u == pytest.approx(-0.25, abs=1e-12)
    assert v == pytest.approx(-0.25, abs=1e-12)
