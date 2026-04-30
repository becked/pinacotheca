"""Layered ground orchestrator for capital + urban renders.

Composites three layers into one PNG, sharing one camera so the layers
align spatially:

    1. Biome base   (TerrainTexturePVTSplat plane from TilePlains_01,
                    Grass_Tile_01_basecolor × Hex_Mask)
    2. Per-nation PVT planes from the capital/urban prefab, sorted by
       `sortingOffset` ascending (Greek mosaic, Egyptian sand roads, etc.)
    3. Existing combined building/clutter parts (top of stack)

Each layer is rendered through the existing `render_mesh_to_image`
pipeline with `bbox_override` set to a shared bbox computed from the
union of all layers' baked vertices, plus `autocrop=False` so the
intermediate frames stay in lockstep. The final composite is autocropped
with the same padding the single-pass path uses.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from pinacotheca.biome_base import BiomeBase
from pinacotheca.prefab import (
    PrefabPart,
    bake_to_obj,
    find_diffuse_for_prefab,
    find_ground_y,
    find_normal_map_for_prefab,
    find_packed_pbr_for_prefab,
    strip_plinth_from_obj,
)
from pinacotheca.pvt_splats import PvtPlanePart, compose_pvt_texture
from pinacotheca.render_metadata import (
    SCHEMA_VERSION,
    GroundHexBounds,
    RenderInfo,
    RenderMetadata,
    WorldBounds,
)
from pinacotheca.renderer import (
    autocrop_with_padding,
    parse_obj,
    render_mesh_to_image,
)

logger = logging.getLogger(__name__)


def _bbox_of_obj(obj_str: str) -> tuple[NDArray[np.float64], NDArray[np.float64]] | None:
    """Return (min, max) of the OBJ vertices in baked render space, or None
    if the OBJ has no vertex lines.
    """
    vertices, _uvs, _normals, _faces, _tangents = parse_obj(obj_str)
    if not vertices:
        return None
    arr = np.asarray(vertices, dtype=np.float64)
    return arr.min(axis=0), arr.max(axis=0)


def _union_bbox(
    bboxes: list[tuple[NDArray[np.float64], NDArray[np.float64]]],
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Union of a list of (min, max) bboxes."""
    mins = np.stack([b[0] for b in bboxes], axis=0)
    maxs = np.stack([b[1] for b in bboxes], axis=0)
    return mins.min(axis=0), maxs.max(axis=0)


def _plane_to_part(plane: PvtPlanePart) -> PrefabPart:
    """Convert a PvtPlanePart to the standard PrefabPart shape `bake_to_obj`
    consumes. We pass an empty materials list — the renderer is given the
    composed `albedo × alpha` texture directly via `texture_image`.
    """
    return PrefabPart(
        mesh_obj=plane.mesh_obj,
        world_matrix=plane.world_matrix,
        materials=[],
    )


def render_layered_ground(
    building_parts: list[PrefabPart],
    pvt_planes: list[PvtPlanePart],
    biome_base: BiomeBase,
    env: Any,
    *,
    width: int = 2048,
    height: int = 2048,
    padding: int = 32,
    pre_rotation_y_deg: float = 180.0,
    extra_building_parts: list[PrefabPart] | None = None,
) -> tuple[Image.Image, RenderMetadata]:
    """Render the three-layer composite for a capital or urban prefab,
    optionally with an extra building layer for urban-improvement
    composites.

    Args:
        building_parts: existing combined parts (after drop_splat_meshes
            and clutter expansion). May be empty if the prefab is purely
            clutter-driven and our walker dropped to zero MeshFilter
            leaves; we still emit ground in that case (just without the
            top layer).
        pvt_planes: per-nation PVT splat planes from the capital/urban
            prefab. May be empty (some MeshFilter capitals lack them).
        biome_base: cached TERRAIN_TEMPERATE base; its `plane` is rendered
            as the bottom layer with its pre-composed `diffuse` as texture.
        env: UnityPy environment, used by `compose_pvt_texture` to resolve
            the per-nation albedo / alpha textures.
        pre_rotation_y_deg: forwarded to every `bake_to_obj` call. Default
            180° matches the buildings convention so all three layers face
            the same way.
        extra_building_parts: optional second buildings group rendered as
            its own layer on top of `building_parts`. Required when the
            two groups come from different material domains (e.g. an
            urban tile's clutter + an improvement's mesh) — baking them
            together would force `find_diffuse_for_prefab` to pick a
            single texture across both, mis-applying it to one group's
            UVs and producing garbled output.

    Returns:
        Tuple of ``(image, metadata)``. ``image`` is the autocropped
        composite. ``metadata`` is tagged ``composition="layered"`` and
        its world bbox covers the full composited scene
        (biome ∪ PVT ∪ buildings); per-ankh should not relative-scale
        layered outputs against per-prefab ones.
    """
    # --- Bake buildings and nation PVT planes first; their union XZ extent
    #     is what we'll scale the biome to cover. The biome prefab
    #     (TilePlains_01) is authored ~18×18 game units which is roughly
    #     two hexes across — much larger than the typical urban/capital
    #     building cluster (~9×9) or per-nation PVT plane (~10–14 across).
    #     In-game that overlap is intentional (adjacent tiles' splats blend),
    #     but for a standalone icon it just leaves a giant empty hex around
    #     the city. Shrinking the biome to the building+PVT footprint puts
    #     the soft Hex_Mask edge right around the rendered content.
    nation_planes_with_texture: list[tuple[PvtPlanePart, str, Image.Image]] = []
    for plane in sorted(pvt_planes, key=lambda p: p.parsed.sorting_offset):
        tex = compose_pvt_texture(env, plane)
        if tex is None:
            logger.warning(
                "Nation PVT plane %r failed to compose; skipping layer",
                plane.host_go_name,
            )
            continue
        plane_obj = bake_to_obj([_plane_to_part(plane)], pre_rotation_y_deg=pre_rotation_y_deg)
        nation_planes_with_texture.append((plane, plane_obj, tex))

    @dataclass(frozen=True)
    class _BakedBuildings:
        obj: str
        tex: Image.Image
        packed_pbr: Image.Image | None
        normal_map: Image.Image | None

    def _bake_group(parts: list[PrefabPart], label: str) -> _BakedBuildings | None:
        if not parts:
            return None
        raw = bake_to_obj(parts, pre_rotation_y_deg=pre_rotation_y_deg)
        cut_y = find_ground_y(parts)
        obj = strip_plinth_from_obj(raw, cut_y_override=cut_y)
        tex = find_diffuse_for_prefab(parts)
        if tex is None:
            logger.warning("%s have no resolvable diffuse texture; skipping layer", label)
            return None
        return _BakedBuildings(
            obj=obj,
            tex=tex,
            packed_pbr=find_packed_pbr_for_prefab(parts),
            normal_map=find_normal_map_for_prefab(parts),
        )

    primary_buildings = _bake_group(building_parts, "Primary buildings")
    extra_buildings = _bake_group(extra_building_parts or [], "Extra buildings")

    # --- Compute target XZ footprint = union of (buildings, nation PVT).
    target_bboxes: list[tuple[NDArray[np.float64], NDArray[np.float64]]] = []
    for _plane, plane_obj, _tex in nation_planes_with_texture:
        bb = _bbox_of_obj(plane_obj)
        if bb is not None:
            target_bboxes.append(bb)
    for baked in (primary_buildings, extra_buildings):
        if baked is None:
            continue
        bb = _bbox_of_obj(baked.obj)
        if bb is not None:
            target_bboxes.append(bb)

    # --- Bake the biome at its authored transform to measure its native
    #     XZ extent, then rescale around origin to match the target.
    biome_part_orig = _plane_to_part(biome_base.plane)
    biome_obj_orig = bake_to_obj([biome_part_orig], pre_rotation_y_deg=pre_rotation_y_deg)
    biome_bbox_orig = _bbox_of_obj(biome_obj_orig)

    biome_obj: str
    if target_bboxes and biome_bbox_orig is not None:
        target_min, target_max = _union_bbox(target_bboxes)
        target_extent_x = float(target_max[0] - target_min[0])
        target_extent_z = float(target_max[2] - target_min[2])
        biome_extent_x = float(biome_bbox_orig[1][0] - biome_bbox_orig[0][0])
        biome_extent_z = float(biome_bbox_orig[1][2] - biome_bbox_orig[0][2])
        # Uniform scale by the larger of the two ratios so the biome covers
        # the target rectangle on both axes (the Hex_Mask alpha falloff
        # pads the corners). Floor at 0.2× to guard against degenerate
        # tiny prefabs producing an invisible biome.
        scale_xz = max(
            0.2,
            min(
                1.0,
                max(target_extent_x / biome_extent_x, target_extent_z / biome_extent_z),
            ),
        )
        scale_matrix = np.diag([scale_xz, 1.0, scale_xz, 1.0]).astype(np.float64)
        biome_part = PrefabPart(
            mesh_obj=biome_base.plane.mesh_obj,
            world_matrix=scale_matrix @ biome_base.plane.world_matrix,
            materials=[],
        )
        biome_obj = bake_to_obj([biome_part], pre_rotation_y_deg=pre_rotation_y_deg)
    else:
        # No buildings or nation PVT to size against — render biome at its
        # authored size.
        biome_obj = biome_obj_orig

    # --- Compute the shared bbox in baked render space across all layers.
    #     Capture the biome bbox separately for the layered sidecar's
    #     `world.groundHex` field so consumers can anchor a hex-clip region
    #     to the ground footprint instead of cover-fitting the whole PNG.
    bboxes: list[tuple[NDArray[np.float64], NDArray[np.float64]]] = []
    biome_bbox = _bbox_of_obj(biome_obj)
    ground_hex_bounds: GroundHexBounds | None = None
    if biome_bbox is not None:
        bboxes.append(biome_bbox)
        bmin, bmax = biome_bbox
        ground_hex_bounds = GroundHexBounds(
            bbox_min=(float(bmin[0]), float(bmin[1]), float(bmin[2])),
            bbox_max=(float(bmax[0]), float(bmax[1]), float(bmax[2])),
        )
    bboxes.extend(target_bboxes)

    if not bboxes:
        raise RuntimeError(
            "render_layered_ground: no renderable geometry across biome, PVT planes, and buildings"
        )
    shared_bbox = _union_bbox(bboxes)

    # --- Render each layer with the shared camera, then alpha-composite.
    composite: Image.Image | None = None

    def _stack(layer: Image.Image) -> None:
        nonlocal composite
        if composite is None:
            composite = layer
        else:
            composite = Image.alpha_composite(composite, layer)

    biome_layer, layer_metadata = render_mesh_to_image(
        biome_obj,
        biome_base.diffuse,
        width=width,
        height=height,
        autocrop=False,
        force_upright=True,
        bbox_override=shared_bbox,
        flat_lighting=True,
    )
    _stack(biome_layer)

    for _plane, plane_obj, tex in nation_planes_with_texture:
        nation_layer, _ = render_mesh_to_image(
            plane_obj,
            tex,
            width=width,
            height=height,
            autocrop=False,
            force_upright=True,
            bbox_override=shared_bbox,
            flat_lighting=True,
        )
        _stack(nation_layer)

    for baked in (primary_buildings, extra_buildings):
        if baked is None:
            continue
        building_layer, _ = render_mesh_to_image(
            baked.obj,
            baked.tex,
            width=width,
            height=height,
            autocrop=False,
            force_upright=True,
            bbox_override=shared_bbox,
            packed_pbr_image=baked.packed_pbr,
            normal_map_image=baked.normal_map,
        )
        _stack(building_layer)

    assert composite is not None
    final_img, cropped_dims_pre_upscale = autocrop_with_padding(composite, padding=padding)

    # Build the layered metadata. All inner layer renders shared
    # `bbox_override=shared_bbox` and `autocrop=False`, so any layer's
    # metadata carries the same framing constants and a
    # `world_units_per_output_pixel` equal to the pre-crop scale. After
    # the final composite autocrop (and possible LANCZOS upscale to
    # min_size), correct for the upscale factor.
    output_w, output_h = final_img.size
    upscale_factor = (
        output_w / cropped_dims_pre_upscale[0] if cropped_dims_pre_upscale[0] > 0 else 1.0
    )
    pre_crop_units_per_pixel = layer_metadata.render.world_units_per_output_pixel
    final_units_per_pixel = pre_crop_units_per_pixel / upscale_factor if upscale_factor > 0 else 0.0

    shared_min, shared_max = shared_bbox
    shared_extent = shared_max - shared_min
    layered_metadata = RenderMetadata(
        version=SCHEMA_VERSION,
        composition="layered",
        world=WorldBounds(
            max_extent=float(shared_extent.max()),
            bbox_min=(float(shared_min[0]), float(shared_min[1]), float(shared_min[2])),
            bbox_max=(float(shared_max[0]), float(shared_max[1]), float(shared_max[2])),
            ground_hex=ground_hex_bounds,
        ),
        framing=layer_metadata.framing,
        render=RenderInfo(
            pre_crop_width_px=int(width),
            pre_crop_height_px=int(height),
            output_width_px=int(output_w),
            output_height_px=int(output_h),
            world_units_per_output_pixel=float(final_units_per_pixel),
        ),
    )

    return final_img, layered_metadata
