"""Synthetic-bytes tests for the TerrainClutterSplat parser + per-channel
mask compositor. Hand-builds minimal MonoBehaviour bodies, no game install
required — CI-safe.
"""

from __future__ import annotations

import struct

import numpy as np
import pytest
from PIL import Image

from pinacotheca.terrain_clutter_splat import (
    ClutterMaskPart,
    TerrainClutterSplatFields,
    compose_clutter_mask_texture,
    parse_terrain_clutter_splat,
)


def _bool_aligned(b: bool) -> bytes:
    return bytes([1 if b else 0]) + b"\x00\x00\x00"


def _i32(v: int) -> bytes:
    return struct.pack("<i", v)


def _f32(v: float) -> bytes:
    return struct.pack("<f", v)


def _pptr(file_id: int, path_id: int) -> bytes:
    return struct.pack("<iq", file_id, path_id)


def _build_clutter_splat_bytes(
    *,
    sorting_offset: int = 12,
    use_simple_mode: bool = True,
    material: tuple[int, int] = (0, 383),
    cluttermask: tuple[int, int] = (0, 2312),
    override_alphamap_use_world_uvs_on: bool = False,
    clutter_mask_channel: int = 2,
    alphamask: tuple[int, int] = (0, 0),
    clear_trees: bool = False,
    clear_minor_buildings: bool = True,
    clear_major_buildings: bool = False,
    clutter_intensity: float = 1.0,
    tiling: float = 1.0,
) -> bytes:
    body = (
        _i32(sorting_offset)
        + _bool_aligned(use_simple_mode)
        + _pptr(*material)
        + _pptr(*cluttermask)
        + _bool_aligned(override_alphamap_use_world_uvs_on)
        + _i32(clutter_mask_channel)
        + _pptr(*alphamask)
        + _bool_aligned(clear_trees)
        + _bool_aligned(clear_minor_buildings)
        + _bool_aligned(clear_major_buildings)
        + _f32(clutter_intensity)
        + _f32(tiling)
    )
    return b"\x00" * 32 + body


def test_round_trip_recovers_all_fields() -> None:
    """Hand-built 72-byte body parses back to the exact field values.
    Values mirror what we observed on the Library Clutter-Mask plane."""
    raw = _build_clutter_splat_bytes(
        sorting_offset=12,
        use_simple_mode=True,
        material=(0, 383),
        cluttermask=(0, 2312),
        clutter_mask_channel=2,
        clear_trees=False,
        clear_minor_buildings=True,
        clear_major_buildings=False,
        clutter_intensity=1.0,
        tiling=1.0,
    )
    assert len(raw) == 32 + 72  # header + body
    f = parse_terrain_clutter_splat(raw)
    assert f.sorting_offset == 12
    assert f.use_simple_mode is True
    assert f.material.path_id == 383
    assert f.cluttermask.path_id == 2312
    assert f.override_alphamap_use_world_uvs_on is False
    assert f.clutter_mask_channel == 2
    assert f.alphamask.is_null()
    assert f.clear_trees is False
    assert f.clear_minor_buildings is True
    assert f.clear_major_buildings is False
    assert f.clutter_intensity == pytest.approx(1.0)
    assert f.tiling == pytest.approx(1.0)


def test_byte_budget_mismatch_raises() -> None:
    """Trailing extra bytes (a future game patch adding a [SerializeField])
    must fail loudly rather than return silently corrupted data."""
    raw = _build_clutter_splat_bytes() + b"\x00\x00\x00\x00"
    with pytest.raises(ValueError, match="raw length"):
        parse_terrain_clutter_splat(raw)


def test_short_body_raises() -> None:
    """Body shorter than expected (e.g. a removed field) must also fail."""
    raw = _build_clutter_splat_bytes()
    truncated = raw[:-4]  # drop trailing tiling float
    with pytest.raises((ValueError, IndexError, struct.error)):
        parse_terrain_clutter_splat(truncated)


def test_each_clear_flag_round_trips_independently() -> None:
    """The three `clear*` flags are separate Unity-serialized bools, each
    consuming 4 bytes (1 byte value + 3 pad). Confirm the layout doesn't
    pack them — flipping each independently must round-trip."""
    for trees, minor, major in [
        (True, False, False),
        (False, True, False),
        (False, False, True),
        (True, True, True),
        (False, False, False),
    ]:
        raw = _build_clutter_splat_bytes(
            clear_trees=trees,
            clear_minor_buildings=minor,
            clear_major_buildings=major,
        )
        f = parse_terrain_clutter_splat(raw)
        assert f.clear_trees is trees
        assert f.clear_minor_buildings is minor
        assert f.clear_major_buildings is major


def test_channel_values_round_trip() -> None:
    """clutter_mask_channel is the ColorChannel enum int (0=R, 1=G, 2=B, 3=A).
    Verify each value parses cleanly so the compositor can index correctly."""
    for channel in (0, 1, 2, 3):
        raw = _build_clutter_splat_bytes(clutter_mask_channel=channel)
        f = parse_terrain_clutter_splat(raw)
        assert f.clutter_mask_channel == channel


# ---- compose_clutter_mask_texture ----


def _make_part(
    *,
    cluttermask_pid: int = 1,
    channel: int = 2,
    intensity: float = 1.0,
    clear_trees: bool = False,
    clear_minor: bool = True,
    clear_major: bool = False,
) -> ClutterMaskPart:
    """Build a ClutterMaskPart with parsed-only fields filled in."""
    from pinacotheca.clutter_transforms import PPtr

    parsed = TerrainClutterSplatFields(
        sorting_offset=0,
        use_simple_mode=True,
        material=PPtr(file_id=0, path_id=0),
        cluttermask=PPtr(file_id=0, path_id=cluttermask_pid),
        override_alphamap_use_world_uvs_on=False,
        clutter_mask_channel=channel,
        alphamask=PPtr(file_id=0, path_id=0),
        clear_trees=clear_trees,
        clear_minor_buildings=clear_minor,
        clear_major_buildings=clear_major,
        clutter_intensity=intensity,
        tiling=1.0,
    )
    return ClutterMaskPart(
        parsed=parsed,
        mesh_obj=None,
        world_matrix=np.eye(4, dtype=np.float64),
        materials=[],
        host_go_name="test",
    )


class _StubReader:
    """Minimal stand-in for the resolved Texture reader; produces a fixed image
    when `parse_as_object` is called, then we monkeypatch `_decode_texture`
    to bypass UnityPy decoding."""

    def __init__(self, payload: object) -> None:
        self._payload = payload

    def parse_as_object(self) -> object:
        return self._payload


def test_compose_writes_only_flagged_channels(monkeypatch: pytest.MonkeyPatch) -> None:
    """A B-channel value of 200 with intensity 1.0, clear_minor only, should
    produce R=0, G=200, B=0 across the output image (G is MinorBuildings)."""
    from pinacotheca import terrain_clutter_splat as mod

    src_arr = np.zeros((4, 4, 4), dtype=np.uint8)
    src_arr[..., 2] = 200  # B channel
    src_img = Image.fromarray(src_arr, mode="RGBA")

    monkeypatch.setattr(mod, "_resolve_pptr_to_reader", lambda _env, _p: _StubReader(src_img))
    monkeypatch.setattr(mod, "_decode_texture", lambda obj: obj)

    part = _make_part(
        channel=2,
        intensity=1.0,
        clear_trees=False,
        clear_minor=True,
        clear_major=False,
    )
    out = compose_clutter_mask_texture(env=None, plane=part)
    assert out is not None
    arr = np.asarray(out)
    assert arr.shape == (4, 4, 3)
    assert (arr[..., 0] == 0).all(), "Trees channel should be 0 (clear_trees=False)"
    assert (arr[..., 1] == 200).all(), "MinorBuildings channel should = mask_value"
    assert (arr[..., 2] == 0).all(), "MajorBuildings channel should be 0 (clear_major=False)"


def test_compose_intensity_scales_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """clutter_intensity multiplies the mask before the per-flag write."""
    from pinacotheca import terrain_clutter_splat as mod

    src_arr = np.zeros((2, 2, 4), dtype=np.uint8)
    src_arr[..., 0] = 100  # R channel
    src_img = Image.fromarray(src_arr, mode="RGBA")
    monkeypatch.setattr(mod, "_resolve_pptr_to_reader", lambda _env, _p: _StubReader(src_img))
    monkeypatch.setattr(mod, "_decode_texture", lambda obj: obj)

    part = _make_part(
        channel=0,
        intensity=0.5,
        clear_trees=True,
        clear_minor=False,
        clear_major=False,
    )
    out = compose_clutter_mask_texture(env=None, plane=part)
    assert out is not None
    arr = np.asarray(out)
    assert (arr[..., 0] == 50).all(), "Trees channel should be mask_value * intensity"


def test_compose_clamps_when_intensity_pushes_past_255(monkeypatch: pytest.MonkeyPatch) -> None:
    """Intensity > 1.0 must clamp at 255 — the cull pass treats values
    monotonically and never wants overflow wrap-around."""
    from pinacotheca import terrain_clutter_splat as mod

    src_arr = np.zeros((2, 2, 4), dtype=np.uint8)
    src_arr[..., 0] = 200
    src_img = Image.fromarray(src_arr, mode="RGBA")
    monkeypatch.setattr(mod, "_resolve_pptr_to_reader", lambda _env, _p: _StubReader(src_img))
    monkeypatch.setattr(mod, "_decode_texture", lambda obj: obj)

    part = _make_part(
        channel=0,
        intensity=2.0,
        clear_trees=True,
        clear_minor=False,
        clear_major=False,
    )
    out = compose_clutter_mask_texture(env=None, plane=part)
    assert out is not None
    arr = np.asarray(out)
    assert (arr[..., 0] == 255).all()


def test_compose_returns_none_on_null_cluttermask() -> None:
    """No cluttermask → log a warning and return None (not a hard error,
    so the cull pass can keep going with whatever planes did resolve)."""
    part = _make_part(cluttermask_pid=0)  # null PPtr
    out = compose_clutter_mask_texture(env=None, plane=part)
    assert out is None
