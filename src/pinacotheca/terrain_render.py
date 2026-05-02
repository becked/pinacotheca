"""Per-(biome, height) terrain tile renderer.

For each ``TerrainTile`` from ``terrain_index.load_terrain_tiles``, this
module composites a final PNG by rendering the appropriate stack of
layers with a shared camera bbox so they align spatially:

* **FLAT land tiles** (TEMPERATE/LUSH/ARID/SAND/TUNDRA/MARSH/URBAN_FLAT):
  one layer — the biome's PVT splat plane composed via
  ``pvt_splats.compose_pvt_texture``, baked via the existing flat path.

* **HILL/MOUNTAIN/VOLCANO**: two layers —
    1. The flat biome PVT ground.
    2. The feature prefab's PVT plane (selected per biome for mountains
       with multiple variants — Snow/Arid/Grass), tessellated to N×N and
       displaced in world Y by the prefab's ``TerrainHeightSplat``
       (``terrain_height_splat.tessellate_displaced_obj``).

* **WATER COAST/OCEAN/LAKE**: one or two layers —
    1. The water tile's PVT plane composed (this IS the visible water
       surface).
    2. Any ``WaterWithFoam`` mesh parts on top, baked flat (oceans and
       coasts have these for surface foam).
  No biome ground; water is its own ground.

Layer rendering pattern is shared with ``layered_render.render_layered_ground``:
each layer goes through ``render_mesh_to_image`` with the same
``bbox_override`` (union of all layers' world bboxes) and
``autocrop=False``, then PIL ``alpha_composite`` stacks them in order.
The final composite is autocropped via ``autocrop_with_padding``. Output
sidecar is tagged ``composition="layered"``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from pinacotheca.biome_base import load_biome_base_from_prefab
from pinacotheca.prefab import (
    PrefabPart,
    bake_to_obj,
    drop_splat_meshes,
    find_diffuse_for_prefab,
    find_normal_map_for_prefab,
    find_packed_pbr_for_prefab,
    find_root_gameobject,
    walk_prefab,
)
from pinacotheca.pvt_splats import (
    PvtPlanePart,
    compose_pvt_texture,
    find_pvt_splats_in_prefab,
)
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
from pinacotheca.terrain_height_splat import (
    HeightSplatPart,
    find_height_splats_in_prefab,
    tessellate_displaced_obj,
)
from pinacotheca.terrain_index import TerrainTile

logger = logging.getLogger(__name__)


# ============================================================
# Mountain biome variant selection
# ============================================================

# TileMountain ships with three PVT planes (MountainSnowPVT,
# MountainAridPVT, MountainGrassPVT). The runtime picks one per the
# underlying biome. For our standalone render, hardcode the mapping.
_MOUNTAIN_PVT_FOR_BIOME: dict[str, str] = {
    "TEMPERATE": "MountainGrassPVT",
    "LUSH": "MountainGrassPVT",
    "MARSH": "MountainGrassPVT",
    "ARID": "MountainAridPVT",
    "SAND": "MountainAridPVT",
    "TUNDRA": "MountainSnowPVT",
}


def _pick_feature_pvt_plane(
    pvt_planes: list[PvtPlanePart], biome: str, height: str
) -> PvtPlanePart | None:
    """Pick the PVT plane on the feature prefab that matches the biome.

    Mountains have 3 variants — pick by host name. Volcanos and hills
    typically have 1 PVT plane — return it. Returns None if no plane
    fits (caller will skip the feature texture layer).
    """
    if not pvt_planes:
        return None
    if height == "MOUNTAIN":
        target_host = _MOUNTAIN_PVT_FOR_BIOME.get(biome)
        if target_host:
            for plane in pvt_planes:
                if plane.host_go_name == target_host:
                    return plane
            logger.warning(
                "MOUNTAIN: biome %s expected host %r but found %s; using first plane",
                biome,
                target_host,
                [p.host_go_name for p in pvt_planes],
            )
    return pvt_planes[0]


# ============================================================
# Layer baking helpers
# ============================================================


@dataclass
class _Layer:
    """One rendered layer ready for alpha-compositing.

    ``obj_str`` is the OBJ already in our right-handed convention.
    ``texture`` is the RGBA diffuse to bind. ``packed_pbr``/``normal_map``
    are optional inputs for the buildings shader (we only set them on
    real-mesh layers like WaterWithFoam — splat-derived layers don't have
    PBR maps).
    """

    obj_str: str
    texture: Image.Image
    packed_pbr: Image.Image | None = None
    normal_map: Image.Image | None = None
    flat_lighting: bool = True


def _flat_pvt_layer(
    plane: PvtPlanePart,
    env: Any,
    *,
    pre_rotation_y_deg: float,
    force_hex_alpha: bool = False,
    scale_xz: float = 1.0,
) -> _Layer | None:
    """Bake a PVT splat plane flat (no displacement) and compose its
    albedo×alpha texture. Returns None on compose failure.

    ``force_hex_alpha=True`` substitutes the canonical ``Hex_Mask`` for
    the prefab's authored alpha — used for the biome-ground bottom layer
    on standalone terrain tiles where the per-biome blend masks
    (``hills_Short_Mask`` etc.) would produce torn-edge splats instead
    of clean hexes.

    ``scale_xz`` shrinks (or grows) the plane in world XZ around its
    pivot. Used by the HILL/MOUNTAIN/VOLCANO render path to fit the
    biome hex tightly around the displaced feature's visible footprint
    so the cone fills most of the hex (matching the in-game look)
    instead of sitting in the middle of a much larger biome quad.
    """
    diffuse = compose_pvt_texture(env, plane, force_hex_alpha=force_hex_alpha)
    if diffuse is None:
        return None
    if scale_xz != 1.0:
        scale_matrix = np.diag([scale_xz, 1.0, scale_xz, 1.0]).astype(np.float64)
        world_matrix = scale_matrix @ plane.world_matrix
    else:
        world_matrix = plane.world_matrix
    obj_str = bake_to_obj(
        [PrefabPart(mesh_obj=plane.mesh_obj, world_matrix=world_matrix, materials=[])],
        pre_rotation_y_deg=pre_rotation_y_deg,
    )
    return _Layer(obj_str=obj_str, texture=diffuse)


def _displaced_pvt_layer(
    plane: PvtPlanePart,
    height_part: HeightSplatPart,
    env: Any,
    *,
    pre_rotation_y_deg: float,
    subdivisions: int = 64,
) -> _Layer | None:
    """Tessellate plane's Quad to a grid, displace by heightmap, compose
    the plane's PVT texture as diffuse. Returns None if tessellation or
    PVT compose fails (caller falls back to a flat layer).
    """
    diffuse = compose_pvt_texture(env, plane)
    if diffuse is None:
        return None
    obj_str = tessellate_displaced_obj(
        env,
        plane.mesh_obj,
        plane.world_matrix,
        height_part,
        subdivisions=subdivisions,
        pre_rotation_y_deg=pre_rotation_y_deg,
    )
    if obj_str is None:
        return None
    return _Layer(obj_str=obj_str, texture=diffuse, flat_lighting=False)


def _mesh_layer(parts: list[PrefabPart], *, pre_rotation_y_deg: float) -> _Layer | None:
    """Bake non-splat mesh parts (e.g. HillsGrass mesh, WaterWithFoam mesh)
    and resolve their diffuse via ``find_diffuse_for_prefab``. Returns
    None if no parts, no diffuse, or empty bake.
    """
    if not parts:
        return None
    diffuse = find_diffuse_for_prefab(parts)
    if diffuse is None:
        return None
    obj_str = bake_to_obj(parts, pre_rotation_y_deg=pre_rotation_y_deg)
    if not obj_str:
        return None
    return _Layer(
        obj_str=obj_str,
        texture=diffuse,
        packed_pbr=find_packed_pbr_for_prefab(parts),
        normal_map=find_normal_map_for_prefab(parts),
        flat_lighting=False,
    )


# ============================================================
# Bbox helpers (mirror of layered_render._bbox_of_obj)
# ============================================================


def _bbox_of_obj(obj_str: str) -> tuple[NDArray[np.float64], NDArray[np.float64]] | None:
    vertices, _uvs, _normals, _faces, _tangents = parse_obj(obj_str)
    if not vertices:
        return None
    arr = np.asarray(vertices, dtype=np.float64)
    return arr.min(axis=0), arr.max(axis=0)


def _displaced_visible_extent_xz(obj_str: str, *, height_fraction: float = 0.1) -> float | None:
    """Return the maximum XZ extent of vertices visibly raised by the
    heightmap displacement (Y > height_fraction × max_Y).

    Used to size the biome hex around the cone's actual visible footprint
    rather than the displaced quad's full mesh extent (which can be 2-3×
    larger and produces a cone-in-empty-hex look — see the
    HILL/MOUNTAIN/VOLCANO biome-scale logic in
    ``_render_hill_mountain_volcano_tile``).

    Returns ``None`` if the OBJ has no vertices or no Y-displaced ones
    (caller falls back to no scaling).
    """
    vertices, *_ = parse_obj(obj_str)
    if not vertices:
        return None
    arr = np.asarray(vertices, dtype=np.float64)
    y = arr[:, 1]
    max_y = float(y.max())
    if max_y <= 0.0:
        return None
    raised = arr[y > max_y * height_fraction]
    if raised.shape[0] == 0:
        return None
    extent_x = float(raised[:, 0].max() - raised[:, 0].min())
    extent_z = float(raised[:, 2].max() - raised[:, 2].min())
    return max(extent_x, extent_z)


def _union_bbox(
    bboxes: list[tuple[NDArray[np.float64], NDArray[np.float64]]],
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    mins = np.stack([b[0] for b in bboxes], axis=0)
    maxs = np.stack([b[1] for b in bboxes], axis=0)
    return mins.min(axis=0), maxs.max(axis=0)


# ============================================================
# Layer composer
# ============================================================


def _render_layers(
    layers: list[_Layer],
    *,
    width: int = 2048,
    height: int = 2048,
    padding: int = 0,
    biome_bbox_for_ground_hex: tuple[NDArray[np.float64], NDArray[np.float64]] | None = None,
    biome_layer_index: int | None = None,
) -> tuple[Image.Image, RenderMetadata]:
    """Render ``layers`` with a shared camera bbox, alpha-composite them
    in order, return the autocropped image + sidecar metadata.

    ``biome_bbox_for_ground_hex`` and ``biome_layer_index``: if set, the
    sidecar's ``world.groundHex`` is built from that bbox + the rendered
    biome layer's pixel-space alpha bbox, mirroring
    ``layered_render.render_layered_ground``. Per-ankh uses ``groundHex``
    to align hex cells.

    ``padding=0`` (vs the codebase-wide default of 32) is intentional for
    terrain: per-ankh consumes these tiles into a hex-grid atlas, and any
    transparent border around the hex shows up as a black gap between
    adjacent cells after their cover-fit step. With padding=0 the source
    image dimensions match the alpha bbox, making cover-fit a no-op.
    Other render paths (improvements, units, etc.) keep the 32 px default
    for visual breathing room in the gallery.
    """
    if not layers:
        raise RuntimeError("_render_layers: no layers")

    # Compute shared world bbox across all layers.
    bboxes: list[tuple[NDArray[np.float64], NDArray[np.float64]]] = []
    for layer in layers:
        bb = _bbox_of_obj(layer.obj_str)
        if bb is not None:
            bboxes.append(bb)
    if not bboxes:
        raise RuntimeError("_render_layers: no renderable geometry")
    shared_bbox = _union_bbox(bboxes)

    composite: Image.Image | None = None
    layer_metadata: RenderMetadata | None = None
    biome_pre_crop_bbox: tuple[int, int, int, int] | None = None

    for idx, layer in enumerate(layers):
        rendered, meta = render_mesh_to_image(
            layer.obj_str,
            layer.texture,
            width=width,
            height=height,
            autocrop=False,
            force_upright=True,
            bbox_override=shared_bbox,
            flat_lighting=layer.flat_lighting,
            packed_pbr_image=layer.packed_pbr,
            normal_map_image=layer.normal_map,
        )
        if layer_metadata is None:
            layer_metadata = meta
        if biome_layer_index is not None and idx == biome_layer_index:
            biome_pre_crop_bbox = rendered.getbbox()
        if composite is None:
            composite = rendered
        else:
            composite = Image.alpha_composite(composite, rendered)

    assert composite is not None
    assert layer_metadata is not None
    final_img, cropped_dims_pre_upscale, crop_origin = autocrop_with_padding(
        composite, padding=padding
    )
    output_w, output_h = final_img.size
    upscale_factor = (
        output_w / cropped_dims_pre_upscale[0] if cropped_dims_pre_upscale[0] > 0 else 1.0
    )
    final_units_per_pixel = (
        layer_metadata.render.world_units_per_output_pixel / upscale_factor
        if upscale_factor > 0
        else 0.0
    )

    ground_hex_bounds: GroundHexBounds | None = None
    if biome_bbox_for_ground_hex is not None:
        bmin, bmax = biome_bbox_for_ground_hex
        pixel_bbox_min: tuple[int, int] | None = None
        pixel_bbox_max: tuple[int, int] | None = None
        if biome_pre_crop_bbox is not None:
            crop_x, crop_y = crop_origin
            x0 = int(round((biome_pre_crop_bbox[0] - crop_x) * upscale_factor))
            y0 = int(round((biome_pre_crop_bbox[1] - crop_y) * upscale_factor))
            x1 = int(round((biome_pre_crop_bbox[2] - crop_x) * upscale_factor))
            y1 = int(round((biome_pre_crop_bbox[3] - crop_y) * upscale_factor))
            pixel_bbox_min = (x0, y0)
            pixel_bbox_max = (x1, y1)
        ground_hex_bounds = GroundHexBounds(
            bbox_min=(float(bmin[0]), float(bmin[1]), float(bmin[2])),
            bbox_max=(float(bmax[0]), float(bmax[1]), float(bmax[2])),
            pixel_bbox_min=pixel_bbox_min,
            pixel_bbox_max=pixel_bbox_max,
        )

    shared_min, shared_max = shared_bbox
    shared_extent = shared_max - shared_min
    metadata = RenderMetadata(
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
    return final_img, metadata


# ============================================================
# Per-tile render strategies
# ============================================================


_PRE_ROTATION_Y_DEG = 180.0


def _render_flat_tile(env: Any, tile: TerrainTile) -> tuple[Image.Image, RenderMetadata]:
    """FLAT land biome — single layer, biome PVT plane composed flat.

    Uses ``force_hex_alpha=True`` so blend-masked biomes
    (LUSH/ARID/TUNDRA/MARSH/URBAN) render as clean hexes instead of
    torn-edge splats — see ``compose_pvt_texture`` for context.
    """
    biome = load_biome_base_from_prefab(env, tile.ground_prefab or "", terrain_z_type=tile.biome)
    layer = _flat_pvt_layer(
        biome.plane, env, pre_rotation_y_deg=_PRE_ROTATION_Y_DEG, force_hex_alpha=True
    )
    if layer is None:
        # compose_pvt_texture returns None — replace with the cached
        # diffuse on biome (which always succeeds since biome was loaded).
        obj_str = bake_to_obj(
            [
                PrefabPart(
                    mesh_obj=biome.plane.mesh_obj,
                    world_matrix=biome.plane.world_matrix,
                    materials=[],
                )
            ],
            pre_rotation_y_deg=_PRE_ROTATION_Y_DEG,
        )
        layer = _Layer(obj_str=obj_str, texture=biome.diffuse)
    biome_bbox = _bbox_of_obj(layer.obj_str)
    return _render_layers(
        [layer],
        biome_bbox_for_ground_hex=biome_bbox,
        biome_layer_index=0,
    )


def _render_hill_mountain_volcano_tile(
    env: Any, tile: TerrainTile
) -> tuple[Image.Image, RenderMetadata]:
    """HILL/MOUNTAIN/VOLCANO: flat biome ground + displaced feature peak.

    The feature prefab's PVT plane is tessellated and displaced via its
    TerrainHeightSplat. For hills, the prefab also has a non-splat mesh
    (HillsGrass) which we render as a third layer on top — but this mesh
    is also flat in the prefab data, so it sits at world Y=0 and shows
    in the cracks where the displaced layer's alpha is low.
    """
    if tile.ground_prefab is None or tile.feature_prefab is None:
        raise ValueError(f"{tile.output_name}: missing ground or feature prefab")

    biome = load_biome_base_from_prefab(env, tile.ground_prefab, terrain_z_type=tile.biome)
    feature_root = find_root_gameobject(env, tile.feature_prefab)
    if feature_root is None:
        raise RuntimeError(f"{tile.output_name}: feature prefab {tile.feature_prefab!r} not found")

    feature_pvt_planes = find_pvt_splats_in_prefab(feature_root)
    feature_pvt = _pick_feature_pvt_plane(feature_pvt_planes, tile.biome, tile.height)
    height_splats = find_height_splats_in_prefab(feature_root)

    # Bake the feature layer first so we can measure its visible (raised)
    # footprint and shrink the biome to match. The feature prefab's mesh
    # quad is typically 1.5–3× wider than its visible cone (the cone is
    # bounded by the heightmap's non-zero region), so without this the
    # cone sits in a much larger biome hex with empty apron — see the
    # tundra-volcano comparison in the docs.
    feature_layer: _Layer | None = None
    if feature_pvt is not None:
        if height_splats:
            feature_layer = _displaced_pvt_layer(
                feature_pvt,
                height_splats[0],
                env,
                pre_rotation_y_deg=_PRE_ROTATION_Y_DEG,
            ) or _flat_pvt_layer(feature_pvt, env, pre_rotation_y_deg=_PRE_ROTATION_Y_DEG)
        else:
            feature_layer = _flat_pvt_layer(
                feature_pvt, env, pre_rotation_y_deg=_PRE_ROTATION_Y_DEG
            )
        if feature_layer is None:
            logger.warning(
                "%s: feature PVT layer failed to compose; rendering ground only",
                tile.output_name,
            )

    # Compute the biome scale-down to fit the cone's visible footprint.
    # Floor at 0.3 (don't shrink to nothing if the heightmap is degenerate);
    # cap at 1.0 (don't upscale a biome that's already smaller than the
    # cone, which can happen on hills with shallow displacement).
    # Apron padding (1.15) leaves a small margin of biome ground around
    # the cone base — purely aesthetic.
    biome_scale_xz = 1.0
    if feature_layer is not None:
        visible_extent = _displaced_visible_extent_xz(feature_layer.obj_str)
        if visible_extent is not None:
            # Measure biome's authored extent at scale=1.0 to compute the
            # ratio. We bake a throwaway PrefabPart for this — fast.
            biome_authored_obj = bake_to_obj(
                [
                    PrefabPart(
                        mesh_obj=biome.plane.mesh_obj,
                        world_matrix=biome.plane.world_matrix,
                        materials=[],
                    )
                ],
                pre_rotation_y_deg=_PRE_ROTATION_Y_DEG,
            )
            biome_authored_bbox = _bbox_of_obj(biome_authored_obj)
            if biome_authored_bbox is not None:
                bmin, bmax = biome_authored_bbox
                biome_extent = float(max(bmax[0] - bmin[0], bmax[2] - bmin[2]))
                if biome_extent > 0:
                    apron_padding = 1.15
                    biome_scale_xz = max(
                        0.3,
                        min(1.0, (visible_extent * apron_padding) / biome_extent),
                    )

    # Layer 1: flat biome ground (with hex alpha + optional shrink).
    biome_layer = _flat_pvt_layer(
        biome.plane,
        env,
        pre_rotation_y_deg=_PRE_ROTATION_Y_DEG,
        force_hex_alpha=True,
        scale_xz=biome_scale_xz,
    )
    if biome_layer is None:
        # Compose failed — fall back to the cached BiomeBase diffuse with
        # a hand-baked obj. Apply the same scale.
        scale_matrix = np.diag([biome_scale_xz, 1.0, biome_scale_xz, 1.0]).astype(np.float64)
        world_matrix = scale_matrix @ biome.plane.world_matrix
        obj_str = bake_to_obj(
            [
                PrefabPart(
                    mesh_obj=biome.plane.mesh_obj,
                    world_matrix=world_matrix,
                    materials=[],
                )
            ],
            pre_rotation_y_deg=_PRE_ROTATION_Y_DEG,
        )
        biome_layer = _Layer(obj_str=obj_str, texture=biome.diffuse)
    layers: list[_Layer] = [biome_layer]
    biome_bbox = _bbox_of_obj(biome_layer.obj_str)

    # Layer 2: feature peak (already baked above).
    if feature_layer is not None:
        layers.append(feature_layer)

    # Layer 3 (hills only): the HillsGrass non-splat mesh on top.
    feature_mesh_parts = drop_splat_meshes(walk_prefab(feature_root))
    # Filter out the PVT plane's own MeshFilter (no materials) so it
    # isn't double-rendered with the wrong texture.
    feature_mesh_parts = [p for p in feature_mesh_parts if p.materials]
    if feature_mesh_parts:
        mesh_layer = _mesh_layer(feature_mesh_parts, pre_rotation_y_deg=_PRE_ROTATION_Y_DEG)
        if mesh_layer is not None:
            layers.append(mesh_layer)

    return _render_layers(
        layers,
        biome_bbox_for_ground_hex=biome_bbox,
        biome_layer_index=0,
    )


# Material property names carrying the water shader's color knobs. The
# WaterWithFoam shader picks one of each per-water-type at runtime; we
# pick the one matching the tile's height field. Verified by dumping
# m_SavedProperties.m_Colors on real TileOcean/TileCoast/TileLake
# materials in the asset bundle.
_WATER_COLOR_PROPERTIES: dict[str, dict[str, str]] = {
    "OCEAN": {
        "transmittance": "_WaterTransmittanceOcean",
        "scattering": "_WaterScatteringOcean",
    },
    "COAST": {
        "transmittance": "_WaterTransmittanceCoast",
        "scattering": "_WaterScatteringCoast",
    },
    "LAKE": {
        "transmittance": "_WaterTransmittanceLake",
        "scattering": "_WaterScatteringLake",
    },
}


def _read_material_color(mat: Any, prop_name: str) -> tuple[float, float, float, float] | None:
    """Read a Color from m_SavedProperties.m_Colors. Returns None if the
    property is missing or any channel is unset (UnityPy renders
    serialized-defaulted-to-zero channels as Python None — treat those
    as 0.0 to keep arithmetic stable)."""
    saved = getattr(mat, "m_SavedProperties", None)
    if saved is None:
        return None
    for entry in getattr(saved, "m_Colors", None) or []:
        if not (isinstance(entry, (tuple, list)) and len(entry) == 2):
            continue
        key, col = entry
        if key != prop_name:
            continue
        # Color may surface as a struct with .r/.g/.b/.a or a dict.
        r = getattr(col, "r", None)
        g = getattr(col, "g", None)
        b = getattr(col, "b", None)
        a = getattr(col, "a", None)
        if r is None and isinstance(col, dict):
            r, g, b, a = col.get("r"), col.get("g"), col.get("b"), col.get("a")
        # Coerce None → 0.0 (Unity stores zero channels as null in some
        # serializations); leave a defaulted to 1.0 if absent.
        return (
            float(r or 0.0),
            float(g or 0.0),
            float(b or 0.0),
            float(a if a is not None else 1.0),
        )
    return None


def _compute_water_diffuse_color(mat: Any, height: str) -> tuple[float, float, float, float]:
    """Approximate the WaterWithFoam shader's resting color for the tile.

    The runtime mixes ``_WaterScattering<Variant>`` (deep-water bounce) and
    ``_WaterTransmittance<Variant>`` (light passing through, sky-tinted)
    based on view depth and density. For a static icon we approximate the
    apparent surface color as ``sky_tint × transmittance + scattering × 0.3``,
    then darken to ~65% to land on a deep-water look matching the game's
    2D water sprite (rather than the over-saturated turquoise the raw
    blend produces — water scatter values have R ≈ 0 and G ≈ B ≈ 0.25,
    which biases pure blends green/cyan).

    Predicted per-type 8-bit RGB on base-game material values:
      OCEAN → (68, 97, 150)  — deep navy
      COAST → (49, 93, 150)  — slightly bluer (less R in coast transmittance)
      LAKE  → (56, 89, 121)  — slight teal lean

    Falls back to a sane default blue if any color property is missing.
    """
    props = _WATER_COLOR_PROPERTIES.get(height)
    if props is None:
        return (0.1, 0.4, 0.65, 1.0)
    scattering = _read_material_color(mat, props["scattering"]) or (0.0, 0.23, 0.25, 1.0)
    transmittance = _read_material_color(mat, props["transmittance"]) or (0.6, 0.85, 0.9, 1.0)
    sky_tint = _read_material_color(mat, "_SkyTint") or (0.47, 0.56, 0.89, 1.0)

    s = np.array(scattering[:3], dtype=np.float64)
    t = np.array(transmittance[:3], dtype=np.float64)
    sk = np.array(sky_tint[:3], dtype=np.float64)
    rgb = np.clip((sk * t + s * 0.3) * 0.65, 0.0, 1.0)
    return (float(rgb[0]), float(rgb[1]), float(rgb[2]), 1.0)


def _solid_color_image(rgba: tuple[float, float, float, float], size: int = 16) -> Image.Image:
    """Return a small solid-color RGBA image. The water mesh has full
    [0, 1] UVs, so any size renders as a uniform fill — keep it tiny."""
    arr = np.zeros((size, size, 4), dtype=np.uint8)
    arr[..., 0] = int(round(rgba[0] * 255))
    arr[..., 1] = int(round(rgba[1] * 255))
    arr[..., 2] = int(round(rgba[2] * 255))
    arr[..., 3] = int(round(rgba[3] * 255))
    return Image.fromarray(arr, mode="RGBA")


def _find_water_surface_parts(water_root: Any) -> list[PrefabPart]:
    """Find the WaterWithFoam / WaterNoFoam mesh parts on the water prefab.

    Bypasses ``drop_splat_meshes`` for these specific materials (which
    treats ``WaterNoFoam`` as a splat and drops it globally). Mesh is the
    6-vertex hex ``Object005``; both ocean and lake authors use it.
    """
    parts: list[PrefabPart] = []
    for p in walk_prefab(water_root):
        if not p.materials:
            continue
        for mat_pptr in p.materials:
            try:
                mat_name = getattr(mat_pptr.read(), "m_Name", "")
            except Exception:
                continue
            if mat_name in ("WaterWithFoam", "WaterNoFoam"):
                parts.append(p)
                break
    return parts


def _water_surface_layer(
    parts: list[PrefabPart], height: str, *, pre_rotation_y_deg: float
) -> _Layer | None:
    """Build a layer for the water surface mesh tinted with the
    per-water-type color computed from the material's saved properties."""
    if not parts:
        return None
    mat = None
    for p in parts:
        for mat_pptr in p.materials or []:
            try:
                m = mat_pptr.read()
                if getattr(m, "m_Name", "") in ("WaterWithFoam", "WaterNoFoam"):
                    mat = m
                    break
            except Exception:
                continue
        if mat is not None:
            break
    if mat is None:
        return None
    rgba = _compute_water_diffuse_color(mat, height)
    diffuse = _solid_color_image(rgba)
    obj_str = bake_to_obj(parts, pre_rotation_y_deg=pre_rotation_y_deg)
    if not obj_str:
        return None
    return _Layer(obj_str=obj_str, texture=diffuse, flat_lighting=True)


def _render_water_tile(env: Any, tile: TerrainTile) -> tuple[Image.Image, RenderMetadata]:
    """WATER COAST/OCEAN/LAKE: tinted water-surface hex.

    The WaterWithFoam (ocean/coast) and WaterNoFoam (lake) materials carry
    the water color as shader properties, not textures (the runtime water
    shader is procedural — sky reflection, transmittance, scattering, foam,
    distortion). We approximate it offline with a flat-color diffuse drawn
    from the material's per-water-type ``_WaterScattering<Variant>`` and
    ``_WaterTransmittance<Variant>`` colors plus ``_SkyTint``. The water
    mesh (``Object005``) is a 6-vertex hex so the layer renders as a
    hex-shaped water surface.

    The seabed PVT plane ("sandy bottom" texture) is intentionally
    skipped — it sits at world Y=0 like the water mesh but is wider
    (18×18 vs 9×10), so including it produces a sandy ring around the
    water hex that adds no information and breaks the icon shape. The
    runtime composes seabed + water + foam + sky reflection, but for a
    static tile icon a clean hex is what consumers want.
    """
    if tile.water_prefab is None:
        raise ValueError(f"{tile.output_name}: missing water_prefab")
    water_root = find_root_gameobject(env, tile.water_prefab)
    if water_root is None:
        raise RuntimeError(f"{tile.output_name}: water prefab {tile.water_prefab!r} not found")

    surface_parts = _find_water_surface_parts(water_root)
    surface_layer = _water_surface_layer(
        surface_parts, tile.height, pre_rotation_y_deg=_PRE_ROTATION_Y_DEG
    )
    if surface_layer is None:
        raise RuntimeError(
            f"{tile.output_name}: no water surface mesh found (prefab={tile.water_prefab!r})"
        )
    biome_bbox = _bbox_of_obj(surface_layer.obj_str)
    return _render_layers(
        [surface_layer],
        biome_bbox_for_ground_hex=biome_bbox,
        biome_layer_index=0,
    )


# ============================================================
# Public entry point
# ============================================================


def render_terrain_tile(env: Any, tile: TerrainTile) -> tuple[Image.Image, RenderMetadata]:
    """Render one (biome, height) tile to a final PNG + sidecar metadata.

    Dispatches to the right per-shape renderer based on which fields of
    ``tile`` are set. All outputs are tagged ``composition="layered"``.
    """
    if tile.water_prefab is not None:
        return _render_water_tile(env, tile)
    if tile.height == "FLAT":
        return _render_flat_tile(env, tile)
    if tile.height in ("HILL", "MOUNTAIN", "VOLCANO"):
        return _render_hill_mountain_volcano_tile(env, tile)
    raise ValueError(
        f"{tile.output_name}: unhandled terrain shape (biome={tile.biome}, height={tile.height})"
    )
