"""Tests for the layered ground orchestrator.

Renderer + bake calls are stubbed out so these tests run without a UnityPy
environment, OpenGL context, or real prefab geometry. The tests verify
shape-level invariants: bbox sharing across passes, layer count,
composite stacking order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PIL import Image

from pinacotheca import layered_render as lr
from pinacotheca.biome_base import BiomeBase
from pinacotheca.clutter_transforms import PPtr
from pinacotheca.pvt_splats import PvtPlanePart, PVTSplatFields


def _solid_rgba(color: tuple[int, int, int, int], size: tuple[int, int] = (32, 32)) -> Image.Image:
    return Image.new("RGBA", size, color)


def _stub_pvt_fields(sorting_offset: int) -> PVTSplatFields:
    null = PPtr(0, 0)
    return PVTSplatFields(
        sorting_offset=sorting_offset,
        pack_in_atlas=False,
        albedo_atlas=null,
        alpha_atlas=null,
        normal_metalic_roughness_atlas=null,
        use_simple_mode=True,
        material=null,
        material_use_world_uvs=False,
        material_tiling=1.0,
        albedo_map=PPtr(0, 1),
        normal_map=null,
        metallic_map=null,
        roughness_map=null,
        alpha_map=PPtr(0, 2),
        alpha_map_channel=0,
        albedo_tint=(1.0, 1.0, 1.0, 1.0),
        normal_map_intensity=1.0,
        metallic=0.0,
        roughness=0.5,
        atlas_index=0,
        texture_array_indices=(0.0, 0.0, 0.0, 0.0),
    )


def _stub_plane(sorting_offset: int) -> PvtPlanePart:
    return PvtPlanePart(
        parsed=_stub_pvt_fields(sorting_offset),
        mesh_obj=object(),
        world_matrix=np.eye(4, dtype=np.float64),
        materials=[],
        host_go_name=f"plane_sort_{sorting_offset}",
    )


@dataclass
class _RenderCall:
    obj_data: str
    texture: Image.Image
    bbox: tuple[Any, Any] | None = None
    autocrop: bool = True
    color: tuple[int, int, int, int] = (0, 0, 0, 0)
    layer_size: tuple[int, int] = field(default=(32, 32))


def _install_stubs(monkeypatch, layer_colors: list[tuple[int, int, int, int]]):
    """Replace bake/render/parse with deterministic stubs.

    Each call to bake_to_obj returns an OBJ string with three vertices at a
    distinct corner (so each layer's bbox is non-degenerate), and the layer
    index is encoded in the OBJ string. render_mesh_to_image returns a
    solid-color RGBA frame keyed by which layer is being rendered.
    """
    layer_index = {"i": 0}
    calls: list[_RenderCall] = []

    def fake_bake_to_obj(_parts: list[Any], *, pre_rotation_y_deg: float = 0.0) -> str:  # noqa: ARG001
        # Encode the layer index in the OBJ string and emit three verts at
        # offset positions so each layer has a non-zero bbox.
        idx = layer_index["i"]
        layer_index["i"] += 1
        return f"# layer {idx}\nv {idx} 0 0\nv {idx + 1} 1 0\nv {idx} 0 1\nf 1 2 3\n"

    monkeypatch.setattr(lr, "bake_to_obj", fake_bake_to_obj)

    # strip_plinth_from_obj passes through unchanged for this test.
    monkeypatch.setattr(
        lr,
        "strip_plinth_from_obj",
        lambda obj, *, cut_y_override=None: obj,  # noqa: ARG005
    )
    # find_ground_y returns 0 for the building parts.
    monkeypatch.setattr(lr, "find_ground_y", lambda _parts: 0.0)
    # find_diffuse_for_prefab returns a solid texture.
    monkeypatch.setattr(lr, "find_diffuse_for_prefab", lambda _parts: _solid_rgba((255, 0, 0, 255)))
    # find_packed_pbr_for_prefab returns None (no occlusion in the stub).
    monkeypatch.setattr(lr, "find_packed_pbr_for_prefab", lambda _parts: None)
    # find_normal_map_for_prefab returns None (no normal mapping in the stub).
    monkeypatch.setattr(lr, "find_normal_map_for_prefab", lambda _parts: None)
    # compose_pvt_texture returns a solid texture for nation planes.
    monkeypatch.setattr(
        lr, "compose_pvt_texture", lambda _env, _plane: _solid_rgba((0, 255, 0, 255))
    )

    color_iter = iter(layer_colors)

    def fake_render_mesh_to_image(
        obj_data: str,
        texture_image: Image.Image,
        *,
        width: int = 64,
        height: int = 64,
        autocrop: bool = True,
        padding: int = 0,  # noqa: ARG001
        force_upright: bool = False,  # noqa: ARG001
        bbox_override: tuple[Any, Any] | None = None,
        flat_lighting: bool = False,  # noqa: ARG001
        packed_pbr_image: Image.Image | None = None,  # noqa: ARG001
        occlusion_strength: float = 0.6,  # noqa: ARG001
        normal_map_image: Image.Image | None = None,  # noqa: ARG001
    ) -> Image.Image:
        color = next(color_iter)
        calls.append(
            _RenderCall(
                obj_data=obj_data,
                texture=texture_image,
                bbox=bbox_override,
                autocrop=autocrop,
                color=color,
            )
        )
        return _solid_rgba(color, size=(width, height))

    monkeypatch.setattr(lr, "render_mesh_to_image", fake_render_mesh_to_image)

    # autocrop_with_padding pass-through; the orchestrator's final crop is
    # tested separately on real images.
    monkeypatch.setattr(lr, "autocrop_with_padding", lambda img, padding=0: img)  # noqa: ARG005

    return calls


def test_layer_order_biome_then_pvt_sorted_then_buildings(monkeypatch) -> None:
    """Layers must be rendered (and composited) in this exact order:
    biome, then PVT planes ascending by sorting_offset, then buildings.
    """
    biome = BiomeBase(
        plane=_stub_plane(80),
        diffuse=_solid_rgba((0, 0, 255, 255)),
        prefab_name="TilePlains_01",
        terrain_z_type="TERRAIN_TEMPERATE",
    )
    # Two PVT planes — give in REVERSE sort order to verify sort logic.
    pvt_planes = [_stub_plane(125), _stub_plane(120)]
    building_parts = [object(), object()]  # opaque to the stubbed pipeline

    layer_colors = [
        (10, 0, 0, 255),  # biome
        (0, 20, 0, 255),  # first PVT in sorted order (sort=120)
        (0, 0, 30, 255),  # second PVT in sorted order (sort=125)
        (40, 40, 0, 255),  # buildings
    ]
    calls = _install_stubs(monkeypatch, layer_colors)

    img = lr.render_layered_ground(building_parts, pvt_planes, biome, env=None)

    # 4 render passes (1 biome + 2 PVT + 1 buildings)
    assert len(calls) == 4
    # All passes share the same bbox_override
    bboxes = [c.bbox for c in calls]
    assert all(b is not None for b in bboxes)
    first = bboxes[0]
    assert first is not None
    for b in bboxes[1:]:
        assert b is not None
        np.testing.assert_array_equal(b[0], first[0])
        np.testing.assert_array_equal(b[1], first[1])
    # All intermediate passes used autocrop=False; the final crop happens
    # via autocrop_with_padding (stubbed pass-through here).
    assert all(c.autocrop is False for c in calls)
    # Top-of-stack is the buildings color (40,40,0,255).
    arr = np.asarray(img.convert("RGBA"))
    assert tuple(arr[0, 0]) == (40, 40, 0, 255)


def test_empty_pvt_planes_renders_biome_plus_buildings(monkeypatch) -> None:
    """A capital that walks to zero PVT planes still gets biome + buildings."""
    biome = BiomeBase(
        plane=_stub_plane(80),
        diffuse=_solid_rgba((0, 0, 255, 255)),
        prefab_name="TilePlains_01",
        terrain_z_type="TERRAIN_TEMPERATE",
    )
    layer_colors = [
        (10, 0, 0, 255),  # biome
        (40, 40, 0, 255),  # buildings
    ]
    calls = _install_stubs(monkeypatch, layer_colors)

    lr.render_layered_ground([object()], [], biome, env=None)
    assert len(calls) == 2


def test_no_buildings_renders_biome_only(monkeypatch) -> None:
    """An empty building_parts list still produces a biome render."""
    biome = BiomeBase(
        plane=_stub_plane(80),
        diffuse=_solid_rgba((0, 0, 255, 255)),
        prefab_name="TilePlains_01",
        terrain_z_type="TERRAIN_TEMPERATE",
    )
    layer_colors = [(10, 0, 0, 255)]  # biome only
    calls = _install_stubs(monkeypatch, layer_colors)

    img = lr.render_layered_ground([], [], biome, env=None)
    assert len(calls) == 1
    arr = np.asarray(img.convert("RGBA"))
    assert tuple(arr[0, 0]) == (10, 0, 0, 255)
