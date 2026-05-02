"""Unit tests for the ClutterTransforms math + expander.

The MonoBehaviour decoder itself is exercised by the smoke test in
`test_typetree.py` against the real game env. These tests cover the
TRS / euler math and the per-instance expander (`clutter_to_prefab_parts*`)
without needing a game install.
"""

from __future__ import annotations

import numpy as np
import pytest

from pinacotheca.clutter_transforms import (
    ClutterInstance,
    ClutterModel,
    ParsedClutterTransforms,
    PPtr,
    euler_to_mat3,
    trs_from_instance,
)


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
    # First column: (rotate * (1,0,0)) * sx = -Z * 2 = (0, 0, -2)
    np.testing.assert_allclose(m[:3, 0], [0.0, 0.0, -2.0], atol=1e-12)
    # Second column: +Y * sy = (0, 1, 0)
    np.testing.assert_allclose(m[:3, 1], [0.0, 1.0, 0.0], atol=1e-12)
    # Third column: +X * sz = (3, 0, 0)
    np.testing.assert_allclose(m[:3, 2], [3.0, 0.0, 0.0], atol=1e-12)


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


def _make_parsed(clutter_type: int, models: tuple[ClutterModel, ...]) -> ParsedClutterTransforms:
    """Minimal ParsedClutterTransforms with non-tiling defaults."""
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

    monkeypatch.setattr(mod, "_resolve_pptr_to_reader", lambda _env, _pptr: _FakeMeshReader())

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

    monkeypatch.setattr(mod, "_resolve_pptr_to_reader", lambda _env, _pptr: _FakeMeshReader())

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

    monkeypatch.setattr(mod, "_resolve_pptr_to_reader", lambda _env, _pptr: _FakeMeshReader())

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
    parts_typed = mod.clutter_to_prefab_parts_with_type(
        env=None, parsed=parsed, parent_world=np.eye(4)
    )
    assert len(parts_legacy) == len(parts_typed) == 2
    for legacy_part, (typed_part, _) in zip(parts_legacy, parts_typed, strict=True):
        np.testing.assert_array_equal(legacy_part.world_matrix, typed_part.world_matrix)
