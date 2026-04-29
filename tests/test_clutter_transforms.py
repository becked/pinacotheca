"""Synthetic-bytes tests for the ClutterTransforms parser and expander.

These tests build minimal MonoBehaviour bodies by hand and feed them
through `parse_clutter_transforms`, plus exercise the TRS / euler math.
No game install required — CI-safe.
"""

from __future__ import annotations

import struct

import numpy as np
import pytest

from pinacotheca.clutter_transforms import (
    ClutterInstance,
    ClutterModel,
    PPtr,
    Reader,
    euler_to_mat3,
    parse_clutter_transforms,
    trs_from_instance,
)

# ============================================================
# Byte builders
# ============================================================


def _bool_aligned(b: bool) -> bytes:
    return bytes([1 if b else 0]) + b"\x00\x00\x00"


def _i32(v: int) -> bytes:
    return struct.pack("<i", v)


def _f32(v: float) -> bytes:
    return struct.pack("<f", v)


def _v2(x: float, y: float) -> bytes:
    return struct.pack("<ff", x, y)


def _v3(x: float, y: float, z: float) -> bytes:
    return struct.pack("<fff", x, y, z)


def _pptr(p: PPtr) -> bytes:
    return struct.pack("<iq", p.file_id, p.path_id)


def _instance_bytes(inst: ClutterInstance) -> bytes:
    return (
        _bool_aligned(inst.initialized)
        + _v3(*inst.position)
        + _v3(*inst.rotation_euler)
        + _v3(*inst.scale)
    )


def _model_bytes(model: ClutterModel) -> bytes:
    out = (
        _bool_aligned(model.initialized)
        + _pptr(model.mesh)
        + _pptr(model.material)
        + _instance_bytes(model.mesh_transform)
        + _i32(model.atlas_index)
        + _i32(len(model.instances))
    )
    for inst in model.instances:
        out += _instance_bytes(inst)
    out += (
        _bool_aligned(model.ignore_heightmap)
        + _bool_aligned(model.use_procedural_damage)
        + _i32(model.clutter_override)
        + _i32(model.lod_quality_level)
        + _bool_aligned(model.show)
    )
    return out


def _build_clutter_bytes(
    *,
    fade_out_when_occupied: bool = False,
    use_static_batching: bool = True,
    use_indirect_instancing: bool = False,
    use_heightmap: bool = True,
    use_world_tiling: bool = False,
    tiling_non_uniform_size: bool = False,
    tiling_zone_size: float = 0.0,
    tiling_zone_size_2d: tuple[float, float] = (0.0, 0.0),
    tiling_mask: PPtr = PPtr(0, 0),
    tiling_mask_breakpoint: float = 0.5,
    tiling_non_uniform_mask_scale: bool = False,
    tiling_mask_size: float = 1.0,
    tiling_mask_size_2d: tuple[float, float] = (1.0, 1.0),
    tiling_mask_channel: int = 0,
    tiling_apply_mask_in_editor: bool = False,
    tiling_preview_mask: bool = False,
    tiling_hide_tiled_copies_in_editor: bool = False,
    tiling_use_world_position_for_offset_in_editor: bool = False,
    tiling_offset_in_editor: tuple[float, float] = (0.0, 0.0),
    override_material: PPtr = PPtr(0, 0),
    clutter_type: int = 0,
    models: tuple[ClutterModel, ...] = (),
    gizmo_radius: float = 0.1,
    selected_index: int = -1,
) -> bytes:
    body = (
        _bool_aligned(fade_out_when_occupied)
        + _bool_aligned(use_static_batching)
        + _bool_aligned(use_indirect_instancing)
        + _bool_aligned(use_heightmap)
        + _bool_aligned(use_world_tiling)
        + _bool_aligned(tiling_non_uniform_size)
        + _f32(tiling_zone_size)
        + _v2(*tiling_zone_size_2d)
        + _pptr(tiling_mask)
        + _f32(tiling_mask_breakpoint)
        + _bool_aligned(tiling_non_uniform_mask_scale)
        + _f32(tiling_mask_size)
        + _v2(*tiling_mask_size_2d)
        + _i32(tiling_mask_channel)
        + _bool_aligned(tiling_apply_mask_in_editor)
        + _bool_aligned(tiling_preview_mask)
        + _bool_aligned(tiling_hide_tiled_copies_in_editor)
        + _bool_aligned(tiling_use_world_position_for_offset_in_editor)
        + _v2(*tiling_offset_in_editor)
        + _pptr(override_material)
        + _i32(clutter_type)
        + _i32(len(models))
    )
    for m in models:
        body += _model_bytes(m)
    body += _f32(gizmo_radius) + _i32(selected_index)
    # 32-byte MonoBehaviour header (zeroed) + body.
    return b"\x00" * 32 + body


# ============================================================
# Reader / euler / TRS unit tests
# ============================================================


def test_reader_bool_alignment() -> None:
    """Unity bool serialization: 1 byte + 3 padding bytes (aligns to 4)."""
    r = Reader(b"\x01\xff\xff\xff\x00\x00\x00\x00")
    assert r.read_bool_aligned() is True
    assert r.pos == 4
    assert r.read_bool_aligned() is False
    assert r.pos == 8


def test_euler_zero_is_identity() -> None:
    np.testing.assert_allclose(euler_to_mat3(0, 0, 0), np.eye(3), atol=1e-12)


def test_euler_y90_rotates_x_to_neg_z() -> None:
    """Unity Quaternion.Euler(0, 90, 0) — column-vector form Ry — rotates +X to -Z.

    Validates the ZXY-intrinsic = YXZ-extrinsic convention: applying Y last
    in our `Ry @ Rx @ Rz` composition.
    """
    m = euler_to_mat3(0, 90, 0)
    rotated = m @ np.array([1.0, 0.0, 0.0])
    np.testing.assert_allclose(rotated, [0.0, 0.0, -1.0], atol=1e-12)


def test_euler_zxy_intrinsic_order() -> None:
    """Verify Z-first then X then Y intrinsic. With Z=90, X=90, Y=0: a vector
    initially along +X is rotated by Z+90 to +Y, then by X+90 to +Z."""
    m = euler_to_mat3(90, 0, 90)
    rotated = m @ np.array([1.0, 0.0, 0.0])
    np.testing.assert_allclose(rotated, [0.0, 0.0, 1.0], atol=1e-12)


def test_trs_from_instance_combines_t_r_s() -> None:
    inst = ClutterInstance(
        initialized=True,
        position=(10.0, 20.0, 30.0),
        rotation_euler=(0.0, 90.0, 0.0),
        scale=(2.0, 1.0, 3.0),
    )
    m = trs_from_instance(inst)
    # Translation
    np.testing.assert_allclose(m[:3, 3], [10.0, 20.0, 30.0])
    # Rotation+scale on column basis vectors. Y-90 maps +X to -Z, +Y unchanged,
    # +Z to +X. Then per-axis scale (2,1,3) is column-wise.
    # First column should be (rotate * (1,0,0)) * sx = -Z * 2 = (0, 0, -2)
    np.testing.assert_allclose(m[:3, 0], [0.0, 0.0, -2.0], atol=1e-12)
    # Second column: +Y * sy = (0, 1, 0)
    np.testing.assert_allclose(m[:3, 1], [0.0, 1.0, 0.0], atol=1e-12)
    # Third column: +X * sz = (3, 0, 0)
    np.testing.assert_allclose(m[:3, 2], [3.0, 0.0, 0.0], atol=1e-12)


# ============================================================
# Parser round-trip tests
# ============================================================


def test_parse_empty_models_round_trip() -> None:
    raw = _build_clutter_bytes(
        fade_out_when_occupied=True,
        use_heightmap=False,
        clutter_type=2,
        models=(),
        gizmo_radius=0.25,
        selected_index=7,
    )
    parsed = parse_clutter_transforms(raw)
    assert parsed.fade_out_when_occupied is True
    assert parsed.use_static_batching is True  # default
    assert parsed.use_heightmap is False
    assert parsed.use_world_tiling is False
    assert parsed.clutter_type == 2
    assert parsed.models == ()
    assert parsed.gizmo_radius == pytest.approx(0.25)
    assert parsed.selected_index == 7


def test_parse_two_models_with_instances() -> None:
    inst_zero = ClutterInstance(
        initialized=False, position=(0, 0, 0), rotation_euler=(0, 0, 0), scale=(1, 1, 1)
    )
    m0 = ClutterModel(
        initialized=True,
        mesh=PPtr(0, 6219),
        material=PPtr(0, 48),
        mesh_transform=inst_zero,
        atlas_index=0,
        instances=(
            ClutterInstance(True, (1.0, 2.0, 3.0), (0.0, 90.0, 0.0), (1.0, 1.0, 1.0)),
            ClutterInstance(True, (4.0, 5.0, 6.0), (45.0, 0.0, 0.0), (2.0, 2.0, 2.0)),
        ),
        ignore_heightmap=False,
        use_procedural_damage=False,
        clutter_override=0,
        lod_quality_level=2,
        show=True,
    )
    m1 = ClutterModel(
        initialized=True,
        mesh=PPtr(0, 5388),
        material=PPtr(0, 48),
        mesh_transform=inst_zero,
        atlas_index=0,
        instances=(),  # zero-instance models are valid
        ignore_heightmap=True,
        use_procedural_damage=False,
        clutter_override=1,
        lod_quality_level=2,
        show=True,
    )
    raw = _build_clutter_bytes(models=(m0, m1))
    parsed = parse_clutter_transforms(raw)
    assert len(parsed.models) == 2

    p0 = parsed.models[0]
    assert p0.mesh == PPtr(0, 6219)
    assert p0.material == PPtr(0, 48)
    assert p0.lod_quality_level == 2
    assert len(p0.instances) == 2
    assert p0.instances[0].position == (1.0, 2.0, 3.0)
    assert p0.instances[1].rotation_euler == (45.0, 0.0, 0.0)

    p1 = parsed.models[1]
    assert p1.ignore_heightmap is True
    assert p1.clutter_override == 1
    assert p1.instances == ()


def test_parse_byte_budget_mismatch_raises() -> None:
    """Trailing extra bytes (i.e. a future game patch added a [SerializeField])
    must fail loudly rather than return silently corrupted data."""
    raw = _build_clutter_bytes(models=()) + b"\x00\x00\x00\x00"
    with pytest.raises(ValueError, match="parse consumed.*delta"):
        parse_clutter_transforms(raw)


def test_parse_implausible_models_count_raises() -> None:
    """If the parser misaligns with reality and reads garbage as the model
    count, the implausible-count guard prevents an infinite loop."""
    # Build a header + scalar block, then a deliberately huge models count.
    bogus = (
        b"\x00" * 32  # MB header
        + b"\x00" * (5 * 4)  # 5 scalars
        + b"\x00" * 76  # TilingProperties
        + _pptr(PPtr(0, 0))  # overrideMaterial
        + _i32(0)  # clutterType
        + _i32(999_999_999)  # implausible count
    )
    with pytest.raises(ValueError, match="Implausible.*models count"):
        parse_clutter_transforms(bogus)


# ============================================================
# clutter_to_prefab_parts_with_type — TerrainClutterType resolution
# ============================================================


class _FakeMeshReader:
    """Stand-in for a UnityPy ObjectReader: resolves to type "Mesh" and
    `parse_as_object` returns itself. Lets `clutter_to_prefab_parts_with_type`
    proceed past the env lookup without a real game install."""

    class _Type:
        def __init__(self, name: str) -> None:
            self.name = name

    def __init__(self, type_name: str = "Mesh") -> None:
        self.type = self._Type(type_name)

    def parse_as_object(self) -> object:
        return self


def _make_parsed(clutter_type: int, models: tuple) -> object:
    """Minimal ParsedClutterTransforms with non-tiling defaults."""
    from pinacotheca.clutter_transforms import ParsedClutterTransforms

    return ParsedClutterTransforms(
        fade_out_when_occupied=False,
        use_static_batching=True,
        use_indirect_instancing=False,
        use_heightmap=True,
        use_world_tiling=False,
        tiling_non_uniform_size=False,
        tiling_zone_size=0.0,
        tiling_zone_size_2d=(0.0, 0.0),
        tiling_mask=PPtr(0, 0),
        tiling_mask_breakpoint=0.5,
        tiling_non_uniform_mask_scale=False,
        tiling_mask_size=1.0,
        tiling_mask_size_2d=(1.0, 1.0),
        tiling_mask_channel=0,
        tiling_apply_mask_in_editor=False,
        tiling_preview_mask=False,
        tiling_hide_tiled_copies_in_editor=False,
        tiling_use_world_position_for_offset_in_editor=False,
        tiling_offset_in_editor=(0.0, 0.0),
        override_material=PPtr(0, 0),
        clutter_type=clutter_type,
        models=models,
        gizmo_radius=0.1,
        selected_index=-1,
    )


def test_clutter_type_falls_back_to_parent_when_override_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When model.clutter_override is None (-1), the per-instance type is
    the parent ClutterTransforms.clutter_type. Mirrors the behavior of
    ClutterTransformsBackgroundData.AddModel."""
    from pinacotheca import clutter_transforms as mod

    monkeypatch.setattr(mod, "_resolve_pptr_to_reader", lambda env, pptr: _FakeMeshReader())

    inst = ClutterInstance(True, (0, 0, 0), (0, 0, 0), (1, 1, 1))
    model = ClutterModel(
        initialized=True,
        mesh=PPtr(0, 1),
        material=PPtr(0, 2),
        mesh_transform=ClutterInstance(False, (0, 0, 0), (0, 0, 0), (1, 1, 1)),
        atlas_index=0,
        instances=(inst, inst, inst),
        ignore_heightmap=False,
        use_procedural_damage=False,
        clutter_override=-1,  # None — fall back to parent
        lod_quality_level=0,
        show=True,
    )
    parsed = _make_parsed(clutter_type=2, models=(model,))  # parent says MajorBuildings(2)

    typed = mod.clutter_to_prefab_parts_with_type(env=None, parsed=parsed, parent_world=np.eye(4))
    assert len(typed) == 3
    for _part, t in typed:
        assert t == 2  # all 3 instances inherit MajorBuildings from parent


def test_clutter_type_uses_per_model_override_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-model override (not -1) wins over the parent's clutter_type."""
    from pinacotheca import clutter_transforms as mod

    monkeypatch.setattr(mod, "_resolve_pptr_to_reader", lambda env, pptr: _FakeMeshReader())

    inst = ClutterInstance(True, (0, 0, 0), (0, 0, 0), (1, 1, 1))
    model_override_trees = ClutterModel(
        initialized=True,
        mesh=PPtr(0, 1),
        material=PPtr(0, 2),
        mesh_transform=ClutterInstance(False, (0, 0, 0), (0, 0, 0), (1, 1, 1)),
        atlas_index=0,
        instances=(inst,),
        ignore_heightmap=False,
        use_procedural_damage=False,
        clutter_override=0,  # Trees
        lod_quality_level=0,
        show=True,
    )
    model_inherits = ClutterModel(
        initialized=True,
        mesh=PPtr(0, 3),
        material=PPtr(0, 4),
        mesh_transform=ClutterInstance(False, (0, 0, 0), (0, 0, 0), (1, 1, 1)),
        atlas_index=0,
        instances=(inst,),
        ignore_heightmap=False,
        use_procedural_damage=False,
        clutter_override=-1,  # inherit parent
        lod_quality_level=0,
        show=True,
    )
    parsed = _make_parsed(clutter_type=1, models=(model_override_trees, model_inherits))

    typed = mod.clutter_to_prefab_parts_with_type(env=None, parsed=parsed, parent_world=np.eye(4))
    assert len(typed) == 2
    assert typed[0][1] == 0  # override → Trees
    assert typed[1][1] == 1  # inherit → MinorBuildings


def test_clutter_to_prefab_parts_returns_same_world_matrices_as_with_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The legacy `clutter_to_prefab_parts` is now defined in terms of the
    typed version — both should produce the same per-instance world matrices
    so capital/urban/resource paths remain bit-equivalent to before."""
    from pinacotheca import clutter_transforms as mod

    monkeypatch.setattr(mod, "_resolve_pptr_to_reader", lambda env, pptr: _FakeMeshReader())

    model = ClutterModel(
        initialized=True,
        mesh=PPtr(0, 1),
        material=PPtr(0, 2),
        mesh_transform=ClutterInstance(False, (0, 0, 0), (0, 0, 0), (1, 1, 1)),
        atlas_index=0,
        instances=(
            ClutterInstance(True, (1, 0, 0), (0, 0, 0), (1, 1, 1)),
            ClutterInstance(True, (2, 0, 0), (0, 0, 0), (1, 1, 1)),
        ),
        ignore_heightmap=False,
        use_procedural_damage=False,
        clutter_override=-1,
        lod_quality_level=0,
        show=True,
    )
    parsed = _make_parsed(clutter_type=0, models=(model,))

    parts_legacy = mod.clutter_to_prefab_parts(env=None, parsed=parsed, parent_world=np.eye(4))
    parts_typed = mod.clutter_to_prefab_parts_with_type(env=None, parsed=parsed, parent_world=np.eye(4))
    assert len(parts_legacy) == len(parts_typed) == 2
    for legacy_part, (typed_part, _) in zip(parts_legacy, parts_typed):
        np.testing.assert_array_equal(legacy_part.world_matrix, typed_part.world_matrix)
