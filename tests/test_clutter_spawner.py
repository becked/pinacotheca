"""Unit tests for the ClutterSpawner adapter + expander.

The MonoBehaviour decoder itself is exercised against the real game env in
the end-to-end render. These tests cover:
  - the typetree dict → dataclass adapter (with a monkeypatched
    `decode_monobehaviour`)
  - empty/hide short-circuits in the expander (no env needed)
  - the procedural layout math against a stubbed env (no game install)

Pure component math (RandomStruct, halton, CPUTexture2D) is covered in
their own test files."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest

from pinacotheca.clutter_spawner import (
    ParsedClutterSpawner,
    SpawnerModel,
    clutter_spawner_to_prefab_parts,
    parse_clutter_spawner,
)
from pinacotheca.clutter_transforms import PPtr


def _typetree_dict_one_model(
    *,
    num_instances: int = 5,
    random_seed: int = 42,
    grid_bounds: tuple[float, float, float, float] = (-1.0, -1.0, 2.0, 2.0),
    texture_mask_path_id: int = 0,
) -> dict[str, Any]:
    """A minimal hand-built typetree dict matching what UnityPy would
    produce for a ClutterSpawner. Models live under `models[*]`; nested
    Vector3/Vector2/Rect dicts use the same key shapes the real
    typetree uses (`x`, `y`, `z`, `width`, `height`)."""
    model = {
        "initialized": 1,
        "mesh": {"m_FileID": 0, "m_PathID": 100},
        "material": {"m_FileID": 0, "m_PathID": 200},
        "materialLayer": 0,
        "sortingOffset": 0,
        "staticBatch": 0,
        "indirectInstance": 0,
        "position": {"x": 0.0, "y": 0.0, "z": 0.0},
        "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
        "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
        "numInstances": num_instances,
        "finalInstances": num_instances,
        "instanceRadius": 0.0,
        "gridBounds": {
            "x": grid_bounds[0],
            "y": grid_bounds[1],
            "width": grid_bounds[2],
            "height": grid_bounds[3],
        },
        "expandRenderingBounds": {"x": 1.0, "y": 1.0, "z": 1.0},
        "textureMask": {"m_FileID": 0, "m_PathID": texture_mask_path_id},
        "textureChannel": 3,
        "clutterType": 0,
        "useWorldRandomness": 0,
        "randomSeed": random_seed,
        "minPosition": {"x": 0.0, "y": 0.0, "z": 0.0},
        "maxPosition": {"x": 0.0, "y": 0.0, "z": 0.0},
        "minRotation": {"x": 0.0, "y": 0.0, "z": 0.0},
        "maxRotation": {"x": 0.0, "y": 0.0, "z": 0.0},
        "minScale": 1.0,
        "maxScale": 1.0,
        "minColor": {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0},
        "maxColor": {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0},
        "textureSheetDimensions": {"x": 1, "y": 1},
        "proceduralDamage": 0,
        "hide": 0,
    }
    return {
        "m_GameObject": {"m_FileID": 0, "m_PathID": 1},
        "m_Enabled": 1,
        "m_Script": {"m_FileID": 0, "m_PathID": 2},
        "m_Name": "",
        "models": [model],
        "useHeightmap": 1,
        "showInstancePoints": 0,
        "hideInstances": 0,
        "showTextureMask": 0,
        "debugOffset": {"x": 0.0, "y": 0.5, "z": 0.0},
    }


# ============================================================
# Adapter
# ============================================================


def test_adapter_extracts_top_level_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    d = _typetree_dict_one_model()
    monkeypatch.setattr(
        "pinacotheca.typetree.decode_monobehaviour",
        lambda _env, _obj, _cls: d,
    )
    parsed = parse_clutter_spawner(env=MagicMock(), obj=MagicMock())
    assert parsed.use_heightmap is True
    assert parsed.hide_instances is False
    assert len(parsed.models) == 1


def test_adapter_extracts_model_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    d = _typetree_dict_one_model(num_instances=120, random_seed=790)
    monkeypatch.setattr(
        "pinacotheca.typetree.decode_monobehaviour",
        lambda _env, _obj, _cls: d,
    )
    parsed = parse_clutter_spawner(env=MagicMock(), obj=MagicMock())
    m = parsed.models[0]
    assert m.num_instances == 120
    assert m.random_seed == 790
    assert m.mesh == PPtr(file_id=0, path_id=100)
    assert m.material == PPtr(file_id=0, path_id=200)
    assert m.texture_mask == PPtr(file_id=0, path_id=0)  # null
    assert m.grid_bounds == (-1.0, -1.0, 2.0, 2.0)
    assert m.position == (0.0, 0.0, 0.0)
    assert m.scale == (1.0, 1.0, 1.0)
    assert m.min_scale == 1.0
    assert m.max_scale == 1.0
    assert m.use_world_randomness is False
    assert m.hide is False


def test_adapter_handles_zero_models(monkeypatch: pytest.MonkeyPatch) -> None:
    d = _typetree_dict_one_model()
    d["models"] = []
    monkeypatch.setattr(
        "pinacotheca.typetree.decode_monobehaviour",
        lambda _env, _obj, _cls: d,
    )
    parsed = parse_clutter_spawner(env=MagicMock(), obj=MagicMock())
    assert parsed.models == ()


# ============================================================
# Expander short-circuits
# ============================================================


def _stub_model(
    *,
    num_instances: int = 5,
    hide: bool = False,
    instance_radius: float = 0.0,
    grid_bounds: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0),
    random_seed: int = 7,
    texture_mask: PPtr = PPtr(file_id=0, path_id=0),  # null by default
) -> SpawnerModel:
    return SpawnerModel(
        mesh=PPtr(file_id=0, path_id=100),
        material=PPtr(file_id=0, path_id=200),
        position=(0.0, 0.0, 0.0),
        rotation_euler=(0.0, 0.0, 0.0),
        scale=(1.0, 1.0, 1.0),
        num_instances=num_instances,
        instance_radius=instance_radius,
        grid_bounds=grid_bounds,
        texture_mask=texture_mask,
        texture_channel=3,
        clutter_type=0,
        use_world_randomness=False,
        random_seed=random_seed,
        min_position=(0.0, 0.0, 0.0),
        max_position=(0.0, 0.0, 0.0),
        min_rotation=(0.0, 0.0, 0.0),
        max_rotation=(0.0, 0.0, 0.0),
        min_scale=1.0,
        max_scale=1.0,
        hide=hide,
    )


def test_expander_returns_empty_when_hide_instances_set() -> None:
    parsed = ParsedClutterSpawner(
        use_heightmap=True,
        hide_instances=True,  # ← global hide
        models=(_stub_model(),),
    )
    parts = clutter_spawner_to_prefab_parts(env=MagicMock(), parsed=parsed, parent_world=np.eye(4))
    assert parts == []


def test_expander_returns_empty_when_all_models_hidden() -> None:
    parsed = ParsedClutterSpawner(
        use_heightmap=True,
        hide_instances=False,
        models=(_stub_model(hide=True),),
    )
    parts = clutter_spawner_to_prefab_parts(env=MagicMock(), parsed=parsed, parent_world=np.eye(4))
    assert parts == []


def test_expander_returns_empty_when_num_instances_zero() -> None:
    parsed = ParsedClutterSpawner(
        use_heightmap=True,
        hide_instances=False,
        models=(_stub_model(num_instances=0),),
    )
    parts = clutter_spawner_to_prefab_parts(env=MagicMock(), parsed=parsed, parent_world=np.eye(4))
    assert parts == []


# ============================================================
# Expander geometry — with stubbed PPtr resolution
# ============================================================


@pytest.fixture
def stub_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub `_resolve_pptr_to_reader` and `_decode_texture` so the expander
    can run without a UnityPy env. Mesh PPtr (path_id=100) resolves to a
    fake Mesh ObjectReader; material PPtr (path_id=200) resolves to a fake
    Material; null PPtr returns None (textureMask path)."""
    mesh_reader = MagicMock()
    mesh_reader.type.name = "Mesh"
    mat_reader = MagicMock()
    mat_reader.type.name = "Material"

    def fake_resolve(_env: Any, pptr: PPtr) -> Any:
        if pptr.is_null():
            return None
        if pptr.path_id == 100:
            return mesh_reader
        if pptr.path_id == 200:
            return mat_reader
        return None

    monkeypatch.setattr("pinacotheca.clutter_spawner._resolve_pptr_to_reader", fake_resolve)


@pytest.mark.usefixtures("stub_resolver")
def test_expander_emits_one_part_per_instance() -> None:
    parsed = ParsedClutterSpawner(
        use_heightmap=True,
        hide_instances=False,
        models=(_stub_model(num_instances=8),),
    )
    parts = clutter_spawner_to_prefab_parts(env=MagicMock(), parsed=parsed, parent_world=np.eye(4))
    assert len(parts) == 8


@pytest.mark.usefixtures("stub_resolver")
def test_expander_world_matrix_falls_inside_grid_bounds() -> None:
    """No random offset, no textureMask, identity per-model TRS, identity
    parent_world → instance positions should be `gridBounds.xy + halton *
    gridBounds.wh`. Halton 2D values are in `[0, 1)` so positions land in
    `[grid_x, grid_x + grid_w) × [grid_z, grid_z + grid_h)`."""
    parsed = ParsedClutterSpawner(
        use_heightmap=True,
        hide_instances=False,
        models=(_stub_model(num_instances=20, grid_bounds=(-2.0, -3.0, 4.0, 5.0)),),
    )
    parts = clutter_spawner_to_prefab_parts(env=MagicMock(), parsed=parsed, parent_world=np.eye(4))
    for p in parts:
        wx = p.world_matrix[0, 3]
        wz = p.world_matrix[2, 3]
        assert -2.0 <= wx < 2.0  # grid_x ≤ wx < grid_x + grid_w
        assert -3.0 <= wz < 2.0  # grid_y ≤ wz < grid_y + grid_h


@pytest.mark.usefixtures("stub_resolver")
def test_expander_is_deterministic_for_same_seed() -> None:
    """Same input dataclass → byte-identical world matrices on repeated runs.
    Critical for stable git diffs of rendered output."""
    parsed = ParsedClutterSpawner(
        use_heightmap=True,
        hide_instances=False,
        models=(_stub_model(num_instances=15, random_seed=999),),
    )
    a = clutter_spawner_to_prefab_parts(env=MagicMock(), parsed=parsed, parent_world=np.eye(4))
    b = clutter_spawner_to_prefab_parts(env=MagicMock(), parsed=parsed, parent_world=np.eye(4))
    assert len(a) == len(b)
    for pa, pb in zip(a, b, strict=True):
        np.testing.assert_array_equal(pa.world_matrix, pb.world_matrix)


@pytest.mark.usefixtures("stub_resolver")
def test_expander_applies_parent_world_translation() -> None:
    """A non-identity parent_world should shift every instance by its
    translation component."""
    parent_world = np.eye(4)
    parent_world[0, 3] = 100.0
    parent_world[2, 3] = 200.0
    parsed = ParsedClutterSpawner(
        use_heightmap=True,
        hide_instances=False,
        models=(_stub_model(num_instances=4, grid_bounds=(0.0, 0.0, 1.0, 1.0)),),
    )
    parts = clutter_spawner_to_prefab_parts(
        env=MagicMock(), parsed=parsed, parent_world=parent_world
    )
    for p in parts:
        assert p.world_matrix[0, 3] >= 100.0
        assert p.world_matrix[0, 3] < 101.0
        assert p.world_matrix[2, 3] >= 200.0
        assert p.world_matrix[2, 3] < 201.0


@pytest.mark.usefixtures("stub_resolver")
def test_expander_instance_radius_drops_overlapping_instances() -> None:
    """A tiny grid + large instanceRadius should reject most instances as
    colliding with their predecessors. The first one is always kept."""
    parsed = ParsedClutterSpawner(
        use_heightmap=True,
        hide_instances=False,
        models=(
            _stub_model(
                num_instances=20,
                # Grid is 0.5×0.5 — very small. Radius = 1.0 covers most of it,
                # so each instance after the first has high odds of colliding.
                grid_bounds=(0.0, 0.0, 0.5, 0.5),
                instance_radius=1.0,
            ),
        ),
    )
    parts = clutter_spawner_to_prefab_parts(env=MagicMock(), parsed=parsed, parent_world=np.eye(4))
    # Without instanceRadius we'd get 20; with radius=1.0 over a 0.5×0.5 grid
    # the second-onwards always collide with the first → exactly 1 kept.
    assert len(parts) == 1


# ============================================================
# apply_texture_mask kwarg
# ============================================================
#
# Vegetation passes `apply_texture_mask=False` to skip the per-tile
# mask CDF remap (`textureMask.GetInverseDensity`) so trees spread
# uniformly across the hex via raw Halton. The default is True for
# the 11 resource prefabs that depend on the mask. These tests verify
# both branches without needing a real Texture2D.


@pytest.mark.usefixtures("stub_resolver")
def test_apply_texture_mask_false_skips_mask_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When `apply_texture_mask=False`, `_resolve_texture_mask` is not
    called even if the model has a non-null textureMask PPtr. Sentinel
    via a fail-loud monkeypatched function."""
    called = {"n": 0}

    def fail_loud(_env: Any, _pptr: PPtr) -> None:
        called["n"] += 1
        raise AssertionError(
            "_resolve_texture_mask should not be called when apply_texture_mask=False"
        )

    monkeypatch.setattr("pinacotheca.clutter_spawner._resolve_texture_mask", fail_loud)
    parsed = ParsedClutterSpawner(
        use_heightmap=True,
        hide_instances=False,
        models=(
            _stub_model(
                num_instances=4,
                # Non-null mask PPtr — would be resolved if the flag were True.
                texture_mask=PPtr(file_id=0, path_id=999),
            ),
        ),
    )
    parts = clutter_spawner_to_prefab_parts(
        env=MagicMock(),
        parsed=parsed,
        parent_world=np.eye(4),
        apply_texture_mask=False,
    )
    assert len(parts) == 4
    assert called["n"] == 0


@pytest.mark.usefixtures("stub_resolver")
def test_apply_texture_mask_default_resolves_mask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default `apply_texture_mask=True` keeps the resource-prefab
    behavior: `_resolve_texture_mask` is invoked exactly once per
    model (even when the PPtr resolves to None and the function
    returns None silently)."""
    called = {"n": 0}

    def stub_resolver_fn(_env: Any, _pptr: PPtr) -> None:
        called["n"] += 1
        return None  # Mask not present → expander still runs uniform Halton.

    monkeypatch.setattr("pinacotheca.clutter_spawner._resolve_texture_mask", stub_resolver_fn)
    parsed = ParsedClutterSpawner(
        use_heightmap=True,
        hide_instances=False,
        models=(_stub_model(num_instances=4, texture_mask=PPtr(file_id=0, path_id=999)),),
    )
    parts = clutter_spawner_to_prefab_parts(
        env=MagicMock(),
        parsed=parsed,
        parent_world=np.eye(4),
        # Default — explicit for clarity.
        apply_texture_mask=True,
    )
    assert len(parts) == 4
    assert called["n"] == 1


@pytest.mark.usefixtures("stub_resolver")
def test_apply_texture_mask_false_preserves_rng_alignment() -> None:
    """The expander always draws the `next_float()` color-lerp value to
    keep its RNG sequence aligned with the runtime; toggling
    `apply_texture_mask` must not shift the per-instance positions.
    With null mask + flag flip we should see byte-identical world
    matrices."""
    parsed = ParsedClutterSpawner(
        use_heightmap=True,
        hide_instances=False,
        models=(_stub_model(num_instances=10, random_seed=12345),),
    )
    a = clutter_spawner_to_prefab_parts(
        env=MagicMock(), parsed=parsed, parent_world=np.eye(4), apply_texture_mask=True
    )
    b = clutter_spawner_to_prefab_parts(
        env=MagicMock(), parsed=parsed, parent_world=np.eye(4), apply_texture_mask=False
    )
    assert len(a) == len(b)
    for pa, pb in zip(a, b, strict=True):
        np.testing.assert_array_equal(pa.world_matrix, pb.world_matrix)
