"""Probabilistic clutter culling for urban-improvement composites.

Replicates the runtime cull pass from
`decompiled/Assembly-CSharp/ClutterTransformsBackgroundData.cs:158-162`:

    if (TerrainPhysics.GetGlobalTerrainHeightData(world_pos, ..., out var result)) {
        if (result.GetClutterChannel(instance.clutterType) > randomStruct.NextFloat()) {
            continue;  // hide this instance
        }
    }

For our offline composite, the per-tile clutter texture is contributed by
each improvement's `TerrainClutterSplat` planes (already composed by
`terrain_clutter_splat.compose_clutter_mask_texture` into a 3-channel image
whose R/G/B encodes Trees/MinorBuildings/MajorBuildings hide-probability).
Multiple planes accumulate via `max` (sufficient because per-channel
hide-probabilities are clamped to [0, 1] and we want the strongest signal
at any position).

`RandomStruct` is a hand port of `decompiled/Mohawk.SystemCore/RandomStruct.cs`
— a Park-Miller LCG with a `seed=0 → ulong.MaxValue` special case.
`RandomStruct(0)` matches the seed used at line 108 of
`ClutterTransformsBackgroundData.PopulateRenderData`, giving deterministic
runs across re-extractions.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from numpy.typing import NDArray

from pinacotheca.clutter_transforms import TERRAIN_CLUTTER_TYPE_NONE
from pinacotheca.prefab import PrefabPart
from pinacotheca.terrain_clutter_splat import (
    ClutterMaskPart,
    compose_clutter_mask_texture,
)

logger = logging.getLogger(__name__)


# ============================================================
# Mohawk.SystemCore.RandomStruct port (Park-Miller LCG)
# ============================================================


_MASK_64 = (1 << 64) - 1
_ULONG_MAX = _MASK_64


class RandomStruct:
    """Faithful port of `Mohawk.SystemCore.RandomStruct` (Park-Miller LCG).

    Constants from the C# source:
        IA = 16807
        IQ = 127773
        IR = 2836

    Seed of 0 is special-cased to `ulong.MaxValue`; nonzero seeds pass
    through. `NextFloat` is `(NextSeed() & 0xFFFF) / 65536f` (ie. uses the
    low 16 bits of the post-update seed).

    All arithmetic uses Python ints masked to 64 bits to match C# `ulong`
    wrap-around (subtraction of `2836 * num` from `16807 * (mulSeed - num*IQ)`
    can underflow when `2836*num > 16807*remainder`).
    """

    __slots__ = ("seed",)

    def __init__(self, seed: int = 0) -> None:
        if seed == 0:
            self.seed = _ULONG_MAX
        else:
            self.seed = seed & _MASK_64

    def next_seed(self) -> int:
        q = self.seed // 127773
        rem = self.seed - q * 127773
        # Subtraction here can underflow in unsigned; mask to 64 bits to wrap.
        new = (16807 * rem - 2836 * q) & _MASK_64
        self.seed = new
        return new

    def next_float(self) -> float:
        return float(self.next_seed() & 0xFFFF) / 65536.0


# ============================================================
# World XZ → mask UV sampling
# ============================================================


def _world_to_local_plane_uv(
    plane_world_inv: NDArray[np.float64],
    world_x: float,
    world_y: float,
    world_z: float,
) -> tuple[float, float] | None:
    """Project a world position into a plane's local Plane-mesh UV space.

    Unity's built-in `Plane` mesh — used by every `TerrainClutterSplat`
    we've inspected (Library, Palace, Theater, Barracks, Royal Library,
    all use mesh PathID=10209/FileID=3 = "Plane") — is a horizontal
    10×10-unit grid in the local XZ plane, normal +Y, with UVs (0, 0) at
    (-5, ?, -5) and (1, 1) at (+5, ?, +5). We invert the plane's world
    matrix to recover local coords, then map local XZ → UV.

    Returns None when the projected UV falls outside [0, 1]^2 (the world
    point is outside the plane's footprint, so the mask contributes 0).
    """
    p = plane_world_inv @ np.array([world_x, world_y, world_z, 1.0], dtype=np.float64)
    u = (float(p[0]) + 5.0) / 10.0
    v = (float(p[2]) + 5.0) / 10.0
    if u < 0.0 or u > 1.0 or v < 0.0 or v > 1.0:
        return None
    return u, v


def _sample_mask_at_uv(
    mask_arr: NDArray[np.uint8],
    u: float,
    v: float,
    channel: int,
) -> float:
    """Sample a 3-channel mask image at (u, v) for one channel, returning a
    value in [0, 1]. Nearest-pixel sampling is fine — the cull is binary and
    per-pixel jitter doesn't matter at this granularity. V flip handles the
    Unity-vs-PIL coordinate convention (Unity V=0 is at texture bottom; PIL
    row 0 is at image top).
    """
    h, w, _ = mask_arr.shape
    px = int(np.clip(u * (w - 1), 0, w - 1))
    py = int(np.clip((1.0 - v) * (h - 1), 0, h - 1))
    return float(mask_arr[py, px, channel]) / 255.0


# ============================================================
# Cull pass
# ============================================================


def cull_clutter_against_masks(
    typed_parts: list[tuple[PrefabPart, int]],
    mask_planes: list[ClutterMaskPart],
    env: Any,
    *,
    seed: int = 0,
) -> list[PrefabPart]:
    """Apply the runtime cull rule to a list of `(PrefabPart, clutter_type)`
    pairs against zero or more `TerrainClutterSplat` planes.

    For each `(part, type)` in iteration order:
      1. Project part's world translation XZ into each mask plane's local UV.
      2. Sample the channel matching its `clutter_type` (R=Trees, G=Minor,
         B=Major). Combine values across overlapping planes via `max`.
      3. Compare against `RandomStruct(seed).next_float()` (one draw per
         instance, in order). If `mask_value > rand`, the instance is hidden.

    Instances with `clutter_type == TerrainClutterType.None` (-1) are never
    culled — they have no channel to sample against. Same for empty
    `mask_planes` (returns `typed_parts` unchanged minus the type tag).

    Iteration order matches the input order; the random sequence is single-
    use across all instances regardless of how many planes contribute.
    """
    rng = RandomStruct(seed)

    if not mask_planes:
        return [p for p, _ in typed_parts]

    # Pre-compose each mask + cache the inverse world matrix for projection.
    composed: list[tuple[NDArray[np.uint8], NDArray[np.float64]]] = []
    for plane in mask_planes:
        img = compose_clutter_mask_texture(env, plane)
        if img is None:
            continue
        try:
            inv = np.linalg.inv(plane.world_matrix).astype(np.float64)
        except np.linalg.LinAlgError:
            logger.warning(
                "TerrainClutterSplat %r world matrix is singular; skipping",
                plane.host_go_name,
            )
            continue
        arr = np.asarray(img, dtype=np.uint8)
        if arr.ndim != 3 or arr.shape[2] != 3:
            logger.warning(
                "TerrainClutterSplat %r mask image has unexpected shape %r; skipping",
                plane.host_go_name,
                arr.shape,
            )
            continue
        composed.append((arr, inv))

    if not composed:
        return [p for p, _ in typed_parts]

    survivors: list[PrefabPart] = []
    for part, clutter_type in typed_parts:
        rand = rng.next_float()  # one draw per instance, regardless of culling
        if clutter_type == TERRAIN_CLUTTER_TYPE_NONE:
            survivors.append(part)
            continue
        if clutter_type < 0 or clutter_type > 2:
            # Unknown channel; safe default is keep.
            survivors.append(part)
            continue

        wx = float(part.world_matrix[0, 3])
        wy = float(part.world_matrix[1, 3])
        wz = float(part.world_matrix[2, 3])

        mask_value = 0.0
        for arr, inv in composed:
            uv = _world_to_local_plane_uv(inv, wx, wy, wz)
            if uv is None:
                continue
            v = _sample_mask_at_uv(arr, uv[0], uv[1], clutter_type)
            if v > mask_value:
                mask_value = v

        if mask_value > rand:
            continue  # hide this instance
        survivors.append(part)

    return survivors
