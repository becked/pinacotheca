"""CPUTexture2D port — `decompiled/Assembly-CSharp/CPUTexture2D.cs`.

Used by the `ClutterSpawner` procedural layout (see `clutter_spawner.py`)
to redistribute Halton-sequence positions through a `textureMask`'s
density. Faithful port of `CalculateInverseDensity` (per-channel
preprocess) and `GetInverseDensity` (per-instance lookup).

How the redistribution works: dense regions of the mask "absorb" more
output slots in the inverseDensity array. A uniform mask gives each
pixel ~1 slot (density passthrough). A mask with one bright pixel
collapses every input UV onto that pixel's center. Inputs are queried
via `get_inverse_density(u, v, channel)`; the integer pixel index drives
the lookup, the sub-pixel fractional offset is preserved as jitter on
top.

# Coordinate frames

UnityPy's `tex.image` returns a PIL image with row 0 at the *top* of
the texture (it has already applied Unity's bottom-left → top-left
flip). The runtime's `CalculateInverseDensity` walks pixels with row
index `k=0` representing v=0 (the *bottom* row in Unity). To make the
algorithm produce the same UV outputs as the runtime, the constructor
flips the image back to Unity's bottom-origin convention via
`np.flipud`. After this flip, pixel `[k, l]` corresponds to UV
`((l+0.5)/width, (k+0.5)/height)` — the same contract the C# source
uses on line 118.
"""

from __future__ import annotations

import math
from enum import IntEnum

import numpy as np
from numpy.typing import NDArray
from PIL import Image


class ColorChannel(IntEnum):
    """Mirror of Unity's `ColorChannel` enum — index into RGBA tuples."""

    R = 0
    G = 1
    B = 2
    A = 3


def _calculate_inverse_density(
    pixels: NDArray[np.float64], width: int, height: int, channel: int
) -> NDArray[np.float64]:
    """Per-channel preprocess; faithful port of `CalculateInverseDensity`.

    Walks pixels in row-major order (k = row, l = column), accumulates
    `pixel[channel] * density_factor`, and emits the current pixel's
    center UV into the next free output slot whenever the accumulator
    crosses 0.5. The number of slots claimed per pixel is
    `Mathf.RoundToInt(accumulator)`; the accumulator retains the
    fractional remainder.

    Output shape is `(width * height, 2)` — a flat list of (u, v) pairs
    in the same row-major layout as the input pixels. Unfilled slots
    remain (0, 0) (matches the C# `new Vector2[pixels.Length]` default).
    """
    n = width * height
    total = float(pixels[..., channel].sum())
    if abs(total) < 1e-9:
        return np.zeros((n, 2), dtype=np.float64)

    density = n / total
    inv_w = 1.0 / width
    inv_h = 1.0 / height
    out = np.zeros((n, 2), dtype=np.float64)

    write = 0
    accumulator = 0.0
    for row in range(height):
        for col in range(width):
            accumulator += float(pixels[row, col, channel]) * density
            if accumulator < 0.5:
                continue
            # Mathf.RoundToInt uses banker's rounding (half-to-even),
            # which is Python's default `round()` for floats.
            count = int(round(accumulator))
            accumulator -= count
            uv_u = (col + 0.5) * inv_w
            uv_v = (row + 0.5) * inv_h
            for _ in range(count):
                if write == n:
                    break
                out[write, 0] = uv_u
                out[write, 1] = uv_v
                write += 1
    return out


class CPUTexture2D:
    """CPU-readable texture wrapper — port of `CPUTexture2D` from C#.

    Construct from a PIL image (typically the output of
    `prefab._decode_texture`). The constructor immediately flips to
    Unity bottom-origin and pre-computes `_calculate_inverse_density`
    for all four channels so per-instance `get_inverse_density` calls
    are O(1).
    """

    __slots__ = ("width", "height", "_pixels", "_inverse_density")

    def __init__(self, image: Image.Image) -> None:
        rgba = image.convert("RGBA")
        # PIL row 0 = top of texture; Unity row 0 = bottom. Flip so that
        # this class indexes the way the C# source expects.
        arr = np.asarray(rgba, dtype=np.uint8)
        arr = np.flipud(arr)
        # Convert to float in [0, 1] — matches Unity's `Color` floats.
        self._pixels: NDArray[np.float64] = arr.astype(np.float64) / 255.0
        self.height: int = int(self._pixels.shape[0])
        self.width: int = int(self._pixels.shape[1])
        self._inverse_density: list[NDArray[np.float64]] = [
            _calculate_inverse_density(self._pixels, self.width, self.height, ch) for ch in range(4)
        ]

    def get_pixel(self, u: float, v: float) -> tuple[float, float, float, float]:
        """Sample at normalized (u, v). Mirrors `GetPixel(float, float)`:
        `floor(u*width)`, `floor(v*height)`, then clamp."""
        x = int(math.floor(u * self.width))
        y = int(math.floor(v * self.height))
        x = max(0, min(self.width - 1, x))
        y = max(0, min(self.height - 1, y))
        r, g, b, a = self._pixels[y, x]
        return float(r), float(g), float(b), float(a)

    def get_inverse_density(
        self, u: float, v: float, channel: ColorChannel | int
    ) -> tuple[float, float]:
        """Map (u, v) through the channel's density array, plus sub-pixel jitter.

        Faithful port of `GetInverseDensity`:
          1. `num = floor(u * width)`, `num2 = floor(v * height)` (Unity
             `Mathf.FloorToInt` rounds toward -inf, matching `math.floor`).
          2. Sub-pixel offsets `num3 = u*width - num - 0.5`,
             `num4 = v*height - num2 - 0.5` — captured *before* clamping
             so out-of-range inputs still preserve their fractional
             component.
          3. Clamp pixel index into `[0, width-1] × [0, height-1]`.
          4. Look up `inverseDensity[channel][num2 * width + num]` and
             add `(num3 * inverseWidth, num4 * inverseHeight)`.
        """
        ch = int(channel)
        num = int(math.floor(u * self.width))
        num2 = int(math.floor(v * self.height))
        num3 = u * self.width - num - 0.5
        num4 = v * self.height - num2 - 0.5
        num = max(0, min(self.width - 1, num))
        num2 = max(0, min(self.height - 1, num2))
        density = self._inverse_density[ch]
        ux, uy = density[num2 * self.width + num]
        return float(ux + num3 / self.width), float(uy + num4 / self.height)
