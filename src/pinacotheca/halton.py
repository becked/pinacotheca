"""Halton low-discrepancy sequence — port of `MathUtilities.HaltonSequence`
and `HaltonSequence2D` from `Mohawk.SystemCore.MathUtilities`.

Used by the `ClutterSpawner` procedural layout (see `clutter_spawner.py`)
to place `numInstances` meshes evenly across `gridBounds` before
per-instance random jitter is applied.

The 2D sequence pairs base 2 and base 3 — that's hardcoded in the C#
source (line 27 of `MathUtilities.cs` initializes the cache as
`new Vector2(HaltonSequence(j, 2), HaltonSequence(j, 3))`).

The C# version memoizes the first 1024 entries; we skip the cache because
the spawner is called with `i + num` indices that frequently exceed 1024
(`num` is a 16-bit hash) and the function is cheap.
"""

from __future__ import annotations


def halton_sequence(index: int, prime: int) -> float:
    """Radical-inverse of `index + 1` in base `prime`.

    Mirrors the C# `HaltonSequence(int index, int prime)`:
    increment index by 1 (so index=0 yields the first sequence value
    rather than 0), then compute the radical inverse digit-by-digit.

    For `index < 0` returns 0 — the C# loop precondition `index > 0`
    short-circuits when the post-increment is non-positive.
    """
    index = index + 1
    result = 0.0
    f = 1.0 / prime
    factor = f
    while index > 0:
        digit = index % prime
        result += digit * factor
        factor *= f
        index //= prime
    return result


def halton_sequence_2d(index: int) -> tuple[float, float]:
    """Pair of base-2 and base-3 Halton values at `index`.

    Equivalent to `MathUtilities.HaltonSequence2D` minus the lookup-table
    short-circuit (we always compute on demand)."""
    return halton_sequence(index, 2), halton_sequence(index, 3)
