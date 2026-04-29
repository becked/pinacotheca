"""Synthetic-bytes tests for the TerrainTexturePVTSplat / TerrainHeightSplat
parsers. These build minimal MonoBehaviour bodies by hand and verify the
field layouts plus body-size drift detection. No game install required —
CI-safe.
"""

from __future__ import annotations

import struct

import pytest

from pinacotheca.pvt_splats import (
    parse_height_splat,
    parse_pvt_splat,
)


def _bool_aligned(b: bool) -> bytes:
    return bytes([1 if b else 0]) + b"\x00\x00\x00"


def _i32(v: int) -> bytes:
    return struct.pack("<i", v)


def _f32(v: float) -> bytes:
    return struct.pack("<f", v)


def _pptr(file_id: int, path_id: int) -> bytes:
    return struct.pack("<iq", file_id, path_id)


def _build_pvt_bytes(
    *,
    sorting_offset: int = 120,
    pack_in_atlas: bool = False,
    albedo_atlas: tuple[int, int] = (0, 0),
    alpha_atlas: tuple[int, int] = (0, 0),
    normal_metalic_roughness_atlas: tuple[int, int] = (0, 0),
    use_simple_mode: bool = True,
    material: tuple[int, int] = (0, 391),
    material_use_world_uvs: bool = False,
    material_tiling: float = 1.0,
    albedo_map: tuple[int, int] = (0, 100),
    normal_map: tuple[int, int] = (0, 0),
    metallic_map: tuple[int, int] = (0, 0),
    roughness_map: tuple[int, int] = (0, 0),
    alpha_map: tuple[int, int] = (0, 200),
    alpha_map_channel: int = 0,
    albedo_tint: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0),
    normal_map_intensity: float = 1.0,
    metallic: float = 0.0,
    roughness: float = 0.5,
    atlas_index: int = 0,
    texture_array_indices: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
) -> bytes:
    body = (
        _i32(sorting_offset)
        + _bool_aligned(pack_in_atlas)
        + _pptr(*albedo_atlas)
        + _pptr(*alpha_atlas)
        + _pptr(*normal_metalic_roughness_atlas)
        + _bool_aligned(use_simple_mode)
        + _pptr(*material)
        + _bool_aligned(material_use_world_uvs)
        + _f32(material_tiling)
        + _pptr(*albedo_map)
        + _pptr(*normal_map)
        + _pptr(*metallic_map)
        + _pptr(*roughness_map)
        + _pptr(*alpha_map)
        + _i32(alpha_map_channel)
        + _f32(albedo_tint[0])
        + _f32(albedo_tint[1])
        + _f32(albedo_tint[2])
        + _f32(albedo_tint[3])
        + _f32(normal_map_intensity)
        + _f32(metallic)
        + _f32(roughness)
        + _i32(atlas_index)
        + _f32(texture_array_indices[0])
        + _f32(texture_array_indices[1])
        + _f32(texture_array_indices[2])
        + _f32(texture_array_indices[3])
    )
    return b"\x00" * 32 + body


def _build_height_bytes(
    *,
    sorting_offset: int = 163,
    use_simple_mode: bool = True,
    material: tuple[int, int] = (0, 387),
    override_world_uv: bool = False,
    intensity: float = 0.7,
    tiling: float = 1.0,
    rgb_heightmap_middle: float = 0.5,
    alphamap_scale_bias: tuple[float, float] = (1.0, 0.0),
    rgb_heightmap: tuple[int, int] = (0, 300),
    heightmap: tuple[int, int] = (0, 0),
) -> bytes:
    body = (
        _i32(sorting_offset)
        + _bool_aligned(use_simple_mode)
        + _pptr(*material)
        + _bool_aligned(override_world_uv)
        + _f32(intensity)
        + _f32(tiling)
        + _f32(rgb_heightmap_middle)
        + _f32(alphamap_scale_bias[0])
        + _f32(alphamap_scale_bias[1])
        + _pptr(*rgb_heightmap)
        + _pptr(*heightmap)
    )
    return b"\x00" * 32 + body


def test_pvt_round_trip_recovers_all_fields() -> None:
    """Hand-built 212-byte PVT body parses back to the exact field values."""
    raw = _build_pvt_bytes(
        sorting_offset=120,
        pack_in_atlas=False,
        use_simple_mode=True,
        material=(0, 391),
        material_use_world_uvs=False,
        material_tiling=1.0,
        albedo_map=(0, 555),
        alpha_map=(0, 666),
        alpha_map_channel=0,
        albedo_tint=(1.0, 1.0, 1.0, 1.0),
        normal_map_intensity=0.30,
        atlas_index=0,
    )
    f = parse_pvt_splat(raw)
    assert f.sorting_offset == 120
    assert f.pack_in_atlas is False
    assert f.use_simple_mode is True
    assert f.material.path_id == 391
    assert f.material_tiling == pytest.approx(1.0)
    assert f.albedo_map.path_id == 555
    assert f.alpha_map.path_id == 666
    assert f.alpha_map_channel == 0
    assert f.albedo_tint == pytest.approx((1.0, 1.0, 1.0, 1.0))
    assert f.normal_map_intensity == pytest.approx(0.30)
    assert f.atlas_index == 0


def test_height_round_trip_recovers_all_fields() -> None:
    """Hand-built 100-byte Height body parses back to the exact field values."""
    raw = _build_height_bytes(
        sorting_offset=163,
        intensity=4.9,
        tiling=2.0,
        rgb_heightmap_middle=0.5,
        alphamap_scale_bias=(1.5, 0.25),
        rgb_heightmap=(0, 777),
        heightmap=(0, 888),
    )
    f = parse_height_splat(raw)
    assert f.sorting_offset == 163
    assert f.intensity == pytest.approx(4.9)
    assert f.tiling == pytest.approx(2.0)
    assert f.rgb_heightmap_middle == pytest.approx(0.5)
    assert f.alphamap_scale_bias == pytest.approx((1.5, 0.25))
    assert f.rgb_heightmap.path_id == 777
    assert f.heightmap.path_id == 888


def test_pvt_byte_budget_mismatch_raises() -> None:
    """Trailing extra bytes (i.e. a future game patch added a [SerializeField])
    must fail loudly rather than return silently corrupted data."""
    raw = _build_pvt_bytes() + b"\x00\x00\x00\x00"
    with pytest.raises(ValueError, match="parse consumed.*delta"):
        parse_pvt_splat(raw)


def test_height_byte_budget_mismatch_raises() -> None:
    """Same drift detection for the Height splat."""
    raw = _build_height_bytes() + b"\x00\x00\x00\x00"
    with pytest.raises(ValueError, match="parse consumed.*delta"):
        parse_height_splat(raw)


def test_pvt_alpha_channel_values_round_trip() -> None:
    """alpha_map_channel is the C# ColorChannel enum int (0=R, 1=G, 2=B, 3=A).
    Verify each value parses cleanly so the compositor can index correctly.
    """
    for channel in (0, 1, 2, 3):
        raw = _build_pvt_bytes(alpha_map_channel=channel)
        f = parse_pvt_splat(raw)
        assert f.alpha_map_channel == channel
