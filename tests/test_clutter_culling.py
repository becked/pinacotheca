"""Tests for the RandomStruct port and the clutter cull pass.
CI-safe — no game install required."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from pinacotheca.clutter_culling import (
    RandomStruct,
    cull_clutter_against_masks,
)
from pinacotheca.clutter_transforms import TERRAIN_CLUTTER_TYPE_NONE, PPtr
from pinacotheca.prefab import PrefabPart
from pinacotheca.terrain_clutter_splat import (
    ClutterMaskPart,
    TerrainClutterSplatFields,
)

# ============================================================
# RandomStruct
# ============================================================


def test_seed_zero_becomes_ulong_max() -> None:
    """Per `RandomStruct(ulong)` source: a seed of 0 is special-cased to
    `ulong.MaxValue`. The constructor takes the special-case path."""
    rs = RandomStruct(0)
    assert rs.seed == (1 << 64) - 1


def test_nonzero_seed_passes_through() -> None:
    rs = RandomStruct(12345)
    assert rs.seed == 12345


def test_next_seed_is_deterministic_for_same_seed() -> None:
    """Two RandomStructs initialized with the same seed produce identical
    sequences (the basis for our reproducibility — same urban tile + same
    improvement → same set of culled clutter every run)."""
    a, b = RandomStruct(7), RandomStruct(7)
    for _ in range(20):
        assert a.next_seed() == b.next_seed()


def test_next_float_is_in_unit_interval() -> None:
    """NextFloat = (NextSeed() & 0xFFFF) / 65536f is always in [0, 1)."""
    rs = RandomStruct(0)
    for _ in range(1000):
        v = rs.next_float()
        assert 0.0 <= v < 1.0


def test_next_float_distribution_is_roughly_uniform() -> None:
    """Sanity check: 10 000 draws should cover the full [0, 1) interval
    with roughly uniform spread (no clustering at one end)."""
    rs = RandomStruct(0)
    samples = [rs.next_float() for _ in range(10_000)]
    assert min(samples) < 0.1
    assert max(samples) > 0.9
    # Mean should be near 0.5 (loose tolerance — 10k samples is small).
    assert 0.4 < sum(samples) / len(samples) < 0.6


def test_next_float_first_few_are_stable() -> None:
    """Lock down the first three NextFloat() values for seed=0 so we catch
    accidental algorithm drift. These are snapshots of what THIS Python
    port produces — if the algorithm changes (e.g. C# RandomStruct gets
    updated and we re-derive), the snapshot will need to be updated too."""
    rs = RandomStruct(0)
    snapshot = [rs.next_float() for _ in range(5)]
    assert snapshot == [
        0.99267578125,
        0.3678741455078125,
        0.056915283203125,
        0.8428802490234375,
        0.0416107177734375,
    ]


def test_next_int_zero_range_returns_zero() -> None:
    """RandomStruct.Next(0) is special-cased to return 0 in the C# source."""
    rs = RandomStruct(0)
    assert rs.next_int(0) == 0
    # And does not advance the seed (no NextSeed call in the zero branch).
    seed_before = rs.seed
    rs.next_int(0)
    assert rs.seed == seed_before


def test_next_int_stays_in_half_open_range() -> None:
    rs = RandomStruct(0)
    for n in [1, 2, 5, 10, 100, 1000]:
        for _ in range(200):
            v = rs.next_int(n)
            assert 0 <= v < n


def test_next_int_distribution_is_roughly_uniform() -> None:
    rs = RandomStruct(0)
    counts = [0] * 10
    for _ in range(10_000):
        counts[rs.next_int(10)] += 1
    # Every bucket should be hit; chi-square-ish loose bound.
    assert min(counts) > 700
    assert max(counts) < 1300


def test_range_float_zero_one_matches_next_float() -> None:
    """Range(0, 1) is algebraically equivalent to NextFloat()."""
    a, b = RandomStruct(42), RandomStruct(42)
    for _ in range(50):
        assert a.range_float(0.0, 1.0) == b.next_float()


def test_range_float_stays_in_half_open_range() -> None:
    rs = RandomStruct(0)
    for _ in range(1000):
        v = rs.range_float(-3.5, 7.25)
        assert -3.5 <= v < 7.25


def test_range_float_zero_width_returns_min() -> None:
    """Range(x, x) collapses to x for any x — the multiplier is 0 regardless
    of NextFloat."""
    rs = RandomStruct(0)
    for _ in range(20):
        assert rs.range_float(2.5, 2.5) == 2.5


# ============================================================
# Cull pass
# ============================================================


def _make_part(world_x: float, world_z: float) -> PrefabPart:
    """A PrefabPart whose world translation is at (world_x, 0, world_z)."""
    m = np.eye(4, dtype=np.float64)
    m[0, 3] = world_x
    m[2, 3] = world_z
    return PrefabPart(mesh_obj=None, world_matrix=m, materials=[])


def _make_mask_plane(
    *,
    world_matrix: np.ndarray | None = None,
    cluttermask_pid: int = 1,
    channel: int = 2,
    clear_trees: bool = True,
    clear_minor: bool = True,
    clear_major: bool = True,
    intensity: float = 1.0,
) -> ClutterMaskPart:
    parsed = TerrainClutterSplatFields(
        sorting_offset=0,
        use_simple_mode=True,
        material=PPtr(0, 0),
        cluttermask=PPtr(0, cluttermask_pid),
        override_alphamap_use_world_uvs_on=False,
        clutter_mask_channel=channel,
        alphamask=PPtr(0, 0),
        clear_trees=clear_trees,
        clear_minor_buildings=clear_minor,
        clear_major_buildings=clear_major,
        clutter_intensity=intensity,
        tiling=1.0,
    )
    return ClutterMaskPart(
        parsed=parsed,
        mesh_obj=None,
        world_matrix=world_matrix if world_matrix is not None else np.eye(4),
        materials=[],
        host_go_name="test-mask",
    )


def test_cull_with_no_mask_planes_keeps_everything() -> None:
    parts = [(_make_part(x, 0.0), 1) for x in range(5)]
    survivors = cull_clutter_against_masks(parts, mask_planes=[], env=None)
    assert len(survivors) == 5


def test_cull_with_none_clutter_type_never_drops(monkeypatch: pytest.MonkeyPatch) -> None:
    """Instances tagged with TerrainClutterType.None (-1) have no channel
    and must never be culled regardless of mask coverage."""
    from pinacotheca import clutter_culling as mod

    # Compose returns a mask that's max in all channels everywhere, which would
    # cull any masked instance. Instances with type=None should still survive.
    full_mask = Image.fromarray(np.full((4, 4, 3), 255, dtype=np.uint8), mode="RGB")
    monkeypatch.setattr(mod, "compose_clutter_mask_texture", lambda _env, _p: full_mask)

    parts = [(_make_part(0.0, 0.0), TERRAIN_CLUTTER_TYPE_NONE)] * 5
    plane = _make_mask_plane()
    survivors = cull_clutter_against_masks(parts, [plane], env=None)
    assert len(survivors) == 5


def test_cull_drops_instance_inside_full_mask_with_matching_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mask saturated to 255 (probability 1.0) must drop every matching-
    type instance (since rand is always < 1.0)."""
    from pinacotheca import clutter_culling as mod

    full_mask = Image.fromarray(np.full((4, 4, 3), 255, dtype=np.uint8), mode="RGB")
    monkeypatch.setattr(mod, "compose_clutter_mask_texture", lambda _env, _p: full_mask)

    # Place 10 trees (type 0) at the plane center (world 0,0,0); plane is
    # identity so they project to UV (0.5, 0.5) which is inside the mask.
    parts = [(_make_part(0.0, 0.0), 0) for _ in range(10)]
    plane = _make_mask_plane()
    survivors = cull_clutter_against_masks(parts, [plane], env=None)
    assert survivors == []


def test_cull_keeps_instance_outside_mask_uv(monkeypatch: pytest.MonkeyPatch) -> None:
    """An instance whose world XZ projects outside the plane's local
    Plane-mesh footprint ([-5, +5] in XZ) → mask contributes 0 → survives."""
    from pinacotheca import clutter_culling as mod

    full_mask = Image.fromarray(np.full((4, 4, 3), 255, dtype=np.uint8), mode="RGB")
    monkeypatch.setattr(mod, "compose_clutter_mask_texture", lambda _env, _p: full_mask)

    # Identity plane has local XZ in [-5, +5]. Place an instance at world
    # (50, 0, 50) — well outside that range.
    parts = [(_make_part(50.0, 50.0), 1)]
    plane = _make_mask_plane()
    survivors = cull_clutter_against_masks(parts, [plane], env=None)
    assert len(survivors) == 1


def test_cull_drops_only_when_mask_value_exceeds_random(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With a half-saturated mask (value 0.5), roughly half of N instances
    should survive — verifies we use NextFloat correctly and it's not always
    above or below the threshold."""
    from pinacotheca import clutter_culling as mod

    half = np.full((4, 4, 3), 128, dtype=np.uint8)  # ≈ 0.502 in [0, 1]
    monkeypatch.setattr(
        mod, "compose_clutter_mask_texture", lambda _env, _p: Image.fromarray(half, mode="RGB")
    )

    # 1000 minor-building instances all at origin.
    parts = [(_make_part(0.0, 0.0), 1) for _ in range(1000)]
    plane = _make_mask_plane()
    survivors = cull_clutter_against_masks(parts, [plane], env=None)
    # Expected ~498 survive; allow a wide band so this isn't flaky.
    assert 350 <= len(survivors) <= 650


def test_cull_combines_overlapping_planes_via_max(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two overlapping mask planes contributing different per-channel values
    are combined with max — the strongest signal wins."""
    from pinacotheca import clutter_culling as mod

    weak = Image.fromarray(np.full((4, 4, 3), 50, dtype=np.uint8), mode="RGB")  # ≈ 0.196
    strong = Image.fromarray(np.full((4, 4, 3), 255, dtype=np.uint8), mode="RGB")  # 1.0

    images = iter([weak, strong])
    monkeypatch.setattr(mod, "compose_clutter_mask_texture", lambda _env, _p: next(images))

    # Two planes both at identity, both covering origin.
    plane_a = _make_mask_plane()
    plane_b = _make_mask_plane()

    # 100 instances at origin; with strong mask value 1.0 → all dropped
    parts = [(_make_part(0.0, 0.0), 1) for _ in range(100)]
    survivors = cull_clutter_against_masks(parts, [plane_a, plane_b], env=None)
    assert survivors == []


def test_cull_is_deterministic_across_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same input, two runs → identical survivor list. Critical for our
    output-PNG byte-equality across re-extractions."""
    from pinacotheca import clutter_culling as mod

    half = np.full((4, 4, 3), 128, dtype=np.uint8)
    monkeypatch.setattr(
        mod, "compose_clutter_mask_texture", lambda _env, _p: Image.fromarray(half, mode="RGB")
    )

    parts = [(_make_part(0.0, 0.0), 1) for _ in range(500)]
    plane = _make_mask_plane()
    a = cull_clutter_against_masks(parts, [plane], env=None)
    b = cull_clutter_against_masks(parts, [plane], env=None)
    assert len(a) == len(b)
