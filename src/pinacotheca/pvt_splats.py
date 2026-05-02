"""TerrainTexturePVTSplat / TerrainHeightSplat decoders, prefab walker,
and per-plane albedo×alpha texture compositor.

Old World authors per-nation ground decoration (Egyptian sand roads, Greek
mosaic, etc.) as `TerrainTexturePVTSplat` MonoBehaviours attached to flat
Quad/Plane meshes inside each capital/urban prefab. At runtime the game's
`TerrainTextureRenderer` bakes them into per-cell terrain textures via an
orthographic top-down camera; for our offline icon path we render each
plane as its own textured quad and composite them in PIL.

MonoBehaviour decode goes through `pinacotheca.typetree` (TypeTreeGenerator
reads the field layout from Assembly-CSharp.dll on demand).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from pinacotheca.clutter_transforms import (
    PPtr,
    _resolve_pptr_to_reader,
    _walk_prefab_with_world,
    script_class,
)
from pinacotheca.prefab import (
    _component_by_type,
    _components_of,
    _decode_texture,
)

logger = logging.getLogger(__name__)


# ============================================================
# Parsed splat data
# ============================================================


@dataclass(frozen=True)
class PVTSplatFields:
    """Decoded body of a TerrainTexturePVTSplat MonoBehaviour."""

    sorting_offset: int
    pack_in_atlas: bool
    albedo_atlas: PPtr
    alpha_atlas: PPtr
    normal_metalic_roughness_atlas: PPtr
    use_simple_mode: bool
    material: PPtr
    material_use_world_uvs: bool
    material_tiling: float
    albedo_map: PPtr
    normal_map: PPtr
    metallic_map: PPtr
    roughness_map: PPtr
    alpha_map: PPtr
    alpha_map_channel: int  # ColorChannel enum: 0=R, 1=G, 2=B, 3=A
    albedo_tint: tuple[float, float, float, float]
    normal_map_intensity: float
    metallic: float
    roughness: float
    atlas_index: int
    texture_array_indices: tuple[float, float, float, float]


@dataclass(frozen=True)
class HeightSplatFields:
    """Decoded body of a TerrainHeightSplat MonoBehaviour."""

    sorting_offset: int
    use_simple_mode: bool
    material: PPtr
    override_world_uv: bool
    intensity: float
    tiling: float
    rgb_heightmap_middle: float
    alphamap_scale_bias: tuple[float, float]
    rgb_heightmap: PPtr
    heightmap: PPtr


@dataclass(frozen=True)
class PvtPlanePart:
    """One TerrainTexturePVTSplat plane found inside a prefab tree.

    `mesh_obj` is the plane GameObject's MeshFilter mesh PPtr (typically a
    Unity built-in Quad or Plane). `world_matrix` is the plane's full
    accumulated TRS so the bake step places it correctly.
    """

    parsed: PVTSplatFields
    mesh_obj: Any  # MeshFilter m_Mesh PPtr — UnityPy native form
    world_matrix: NDArray[np.float64]
    materials: list[Any]  # MeshRenderer m_Materials, for diagnostics
    host_go_name: str


# ============================================================
# Decoders
# ============================================================


def _adapt_pptr(d: dict[str, Any]) -> PPtr:
    return PPtr(file_id=int(d["m_FileID"]), path_id=int(d["m_PathID"]))


def parse_pvt_splat(env: Any, obj: Any) -> PVTSplatFields:
    """Decode a TerrainTexturePVTSplat MonoBehaviour into the dataclass shape."""
    from pinacotheca.typetree import decode_monobehaviour

    d = decode_monobehaviour(env, obj, "TerrainTexturePVTSplat")
    tint = d["albedoTint"]
    tai = d["textureArrayIndices"]
    return PVTSplatFields(
        sorting_offset=int(d["sortingOffset"]),
        pack_in_atlas=bool(d["packInAtlas"]),
        albedo_atlas=_adapt_pptr(d["albedoAtlas"]),
        alpha_atlas=_adapt_pptr(d["alphaAtlas"]),
        normal_metalic_roughness_atlas=_adapt_pptr(d["normalMetalicRoughnessAtlas"]),
        use_simple_mode=bool(d["useSimpleMode"]),
        material=_adapt_pptr(d["material"]),
        material_use_world_uvs=bool(d["materialUseWorldUVs"]),
        material_tiling=float(d["materialTiling"]),
        albedo_map=_adapt_pptr(d["albedoMap"]),
        normal_map=_adapt_pptr(d["normalMap"]),
        metallic_map=_adapt_pptr(d["metallicMap"]),
        roughness_map=_adapt_pptr(d["roughnessMap"]),
        alpha_map=_adapt_pptr(d["alphaMap"]),
        alpha_map_channel=int(d["alphaMapChannel"]),
        albedo_tint=(float(tint["r"]), float(tint["g"]), float(tint["b"]), float(tint["a"])),
        normal_map_intensity=float(d["normalMapIntensity"]),
        metallic=float(d["metallic"]),
        roughness=float(d["roughness"]),
        atlas_index=int(d["atlasIndex"]),
        texture_array_indices=(
            float(tai["x"]),
            float(tai["y"]),
            float(tai["z"]),
            float(tai["w"]),
        ),
    )


def parse_height_splat(env: Any, obj: Any) -> HeightSplatFields:
    """Decode a TerrainHeightSplat MonoBehaviour into the dataclass shape."""
    from pinacotheca.typetree import decode_monobehaviour

    d = decode_monobehaviour(env, obj, "TerrainHeightSplat")
    bias = d["alphamapScaleBias"]
    return HeightSplatFields(
        sorting_offset=int(d["sortingOffset"]),
        use_simple_mode=bool(d["useSimpleMode"]),
        material=_adapt_pptr(d["material"]),
        override_world_uv=bool(d["overrideWorldUvIsOn"]),
        intensity=float(d["intensity"]),
        tiling=float(d["tiling"]),
        rgb_heightmap_middle=float(d["rgbHeightmapMiddle"]),
        alphamap_scale_bias=(float(bias["x"]), float(bias["y"])),
        rgb_heightmap=_adapt_pptr(d["rgbHeightmap"]),
        heightmap=_adapt_pptr(d["heightmap"]),
    )


# ============================================================
# Prefab-tree walker
# ============================================================


def find_pvt_splats_in_prefab(root_go: Any) -> list[PvtPlanePart]:
    """Descend the prefab tree, find every TerrainTexturePVTSplat plane,
    pair each with its host GameObject's MeshFilter mesh + world matrix.

    Find by script class, not GameObject name — names vary across nations
    (`GreeceCapitalPVT`, `RomePVT`, `landBabylon` etc.) and the prefab tree
    can have nested same-name children (Egypt). Side-effect: parses any
    TerrainHeightSplat we see (drift detection) but does not return them —
    the height layer is not rendered today.
    """
    found: list[PvtPlanePart] = []
    for go, world in _walk_prefab_with_world(root_go):
        pvt_parsed: PVTSplatFields | None = None
        for pptr in _components_of(go):
            try:
                r = pptr.deref()
                if r.type.name != "MonoBehaviour":
                    continue
            except Exception:
                continue
            try:
                cls = script_class(r)
            except Exception:
                continue
            if cls == "TerrainTexturePVTSplat":
                try:
                    pvt_parsed = parse_pvt_splat(r.assets_file.parent, r)
                except Exception as e:
                    logger.warning("TerrainTexturePVTSplat decode failed: %s", e)
                    continue
            elif cls == "TerrainHeightSplat":
                try:
                    # Decode for drift detection; result is discarded.
                    parse_height_splat(r.assets_file.parent, r)
                except Exception as e:
                    logger.warning("TerrainHeightSplat decode failed: %s", e)
                    continue

        if pvt_parsed is None:
            continue

        mf = _component_by_type(go, "MeshFilter")
        if mf is None:
            logger.warning(
                "TerrainTexturePVTSplat on %r has no MeshFilter sibling; skipping",
                getattr(go, "m_Name", "?"),
            )
            continue
        mf_mesh = getattr(mf, "m_Mesh", None)
        if mf_mesh is None or not bool(mf_mesh):
            logger.warning(
                "TerrainTexturePVTSplat on %r has MeshFilter with null mesh; skipping",
                getattr(go, "m_Name", "?"),
            )
            continue

        materials: list[Any] = []
        mr = _component_by_type(go, "MeshRenderer")
        if mr is not None:
            for mp in getattr(mr, "m_Materials", None) or []:
                if bool(mp):
                    materials.append(mp)

        found.append(
            PvtPlanePart(
                parsed=pvt_parsed,
                mesh_obj=mf_mesh,
                world_matrix=world.copy(),
                materials=materials,
                host_go_name=str(getattr(go, "m_Name", "?")),
            )
        )
    return found


# ============================================================
# Texture compositor
# ============================================================


_HEX_MASK_CACHE: Image.Image | None = None

# Procedural hex mask resolution. Big enough to anti-alias cleanly when
# projected through the renderer's 45°-tilt camera onto a ~15-unit world
# quad; small enough to compose quickly. Asset Hex_Mask is 512×512 — we
# use 1024 for slightly crisper edges in the output.
_HEX_MASK_SIZE = 1024


def _generate_hex_mask(size: int = _HEX_MASK_SIZE) -> Image.Image:
    """Generate a point-up regular hexagon mask in numpy.

    Returns an "L"-mode PIL image with white interior, black exterior,
    and ~1px of anti-aliasing on the boundary. Hex is inscribed in the
    square texture: vertical extent (vertex-to-vertex) fills the height;
    horizontal extent (apothem-to-apothem) is √3/2 ≈ 0.866 of the width.
    Used in place of the asset bundle's authored ``Hex_Mask`` texture,
    which has ~30 px of soft falloff baked in (designed for runtime
    blending into neighboring tile splats — not what we want for a
    standalone tile icon).

    A point-up hex (vertex at top/bottom, flat sides on left/right) at
    circumradius R has 3 unique edge-normal directions; a point is inside
    iff its absolute projection onto each is ≤ apothem (R·cos 30° = √3/2).
    """
    # Coordinate grid centered at origin; image rows are inverted vs world
    # but the hex is symmetric so it doesn't matter. Range: [-1, 1] on
    # both axes so circumradius R = 1.
    coord = np.linspace(-1.0, 1.0, size, dtype=np.float64)
    y, x = np.meshgrid(coord, coord, indexing="ij")

    # Three unique edge-normal directions (the other three are antipodes;
    # taking abs() of the projection collapses the pair):
    #   n0 = (1, 0)              — left/right edges
    #   n1 = (1/2,  √3/2)        — upper-right / lower-left edges
    #   n2 = (-1/2, √3/2)        — upper-left / lower-right edges
    sqrt3_2 = np.sqrt(3.0) / 2.0
    p0 = np.abs(x)
    p1 = np.abs(0.5 * x + sqrt3_2 * y)
    p2 = np.abs(-0.5 * x + sqrt3_2 * y)
    max_proj = np.maximum(np.maximum(p0, p1), p2)

    apothem = sqrt3_2  # = R · cos(30°) with R = 1

    # Linear ramp from 1.0 (well inside) to 0.0 (well outside) across a
    # ~1 pixel-wide boundary. `1.5/size` gives ≈1.5 image-pixel feather.
    feather = 1.5 / size
    alpha = np.clip((apothem - max_proj) / feather + 0.5, 0.0, 1.0)
    alpha_u8 = (alpha * 255.0).astype(np.uint8)
    return Image.fromarray(alpha_u8, mode="L")


def load_hex_mask(env: Any) -> Image.Image | None:  # noqa: ARG001
    """Return a hard-edged hex-shaped alpha mask for the canonical
    standalone terrain-tile shape. Cached after first call.

    Generated procedurally rather than loaded from the asset bundle's
    ``Hex_Mask`` Texture2D — the asset's authored falloff is ~30 pixels
    wide (designed to blend into neighboring tile splats at runtime),
    which produces an oval/round look rather than a clean hexagon when
    used as the standalone-tile alpha. The procedural variant is a true
    point-up regular hexagon with ~1px anti-aliasing.

    The ``env`` parameter is unused (kept for API compatibility with
    older callers that expected an asset-lookup signature) — pass any
    truthy value or ``None``.
    """
    global _HEX_MASK_CACHE
    if _HEX_MASK_CACHE is None:
        _HEX_MASK_CACHE = _generate_hex_mask()
    return _HEX_MASK_CACHE


def compose_pvt_texture(
    env: Any,
    plane: PvtPlanePart,
    *,
    force_hex_alpha: bool = False,
) -> Image.Image | None:
    """Compose a single RGBA texture for one PVT plane: albedo × alpha tint.

    Resolves the parsed albedo_map and alpha_map PPtrs, decodes both, and
    produces an RGBA PIL image where:
      out.rgb = albedo.rgb * tint.rgb
      out.a   = alpha[channel] * tint.a

    Channel selection follows the parsed `alpha_map_channel` int against
    the C# `ColorChannel` enum (verified `decompiled/Assembly-CSharp/
    ColorChannel.cs`: 0=R, 1=G, 2=B, 3=A). `material_tiling` is intentionally
    not honored at this stage — mesh UVs already encode the authored layout.

    When ``force_hex_alpha=True``, the prefab's authored alpha map is
    ignored and the canonical ``Hex_Mask`` (R channel) is used instead —
    the biome-ground composite path for standalone terrain-tile renders
    uses this so blend-masked biomes (LUSH/ARID/TUNDRA/MARSH/URBAN, which
    ship with torn-edge ``hills_Short_Mask`` / similar) come out as clean
    hexes the way TEMPERATE/SAND already do. Albedo is unchanged.

    Returns None (and logs a warning) if either texture PPtr is null,
    fails to resolve, or fails to decode. The renderer's alpha-cutout
    fragment shader (alpha < 0.5 discard) handles the transparent regions
    in the final composite.
    """
    p = plane.parsed
    if p.albedo_map.is_null():
        logger.warning("PVT plane %r has null albedo_map; skipping", plane.host_go_name)
        return None
    if p.alpha_map.is_null() and not force_hex_alpha:
        logger.warning("PVT plane %r has null alpha_map; skipping", plane.host_go_name)
        return None

    albedo_reader = _resolve_pptr_to_reader(env, p.albedo_map)
    if albedo_reader is None:
        logger.warning("PVT plane %r albedo_map did not resolve", plane.host_go_name)
        return None

    try:
        albedo_tex = albedo_reader.parse_as_object()
    except Exception as e:
        logger.warning("PVT plane %r albedo parse failed: %s", plane.host_go_name, e)
        return None

    albedo_img = _decode_texture(albedo_tex)
    if albedo_img is None:
        logger.warning("PVT plane %r albedo decode failed", plane.host_go_name)
        return None

    alpha_img: Image.Image | None
    channel: int
    if force_hex_alpha:
        alpha_img = load_hex_mask(env)
        channel = 0  # Hex_Mask is delivered as a single-channel ("L") image
    else:
        alpha_reader = _resolve_pptr_to_reader(env, p.alpha_map)
        if alpha_reader is None:
            logger.warning("PVT plane %r alpha_map did not resolve", plane.host_go_name)
            return None
        try:
            alpha_tex = alpha_reader.parse_as_object()
        except Exception as e:
            logger.warning("PVT plane %r alpha parse failed: %s", plane.host_go_name, e)
            return None
        alpha_img = _decode_texture(alpha_tex)
        channel = max(0, min(3, int(p.alpha_map_channel)))
    if alpha_img is None:
        logger.warning("PVT plane %r alpha decode failed", plane.host_go_name)
        return None

    # Match albedo and alpha resolution. Alphamap is sometimes a different
    # size from the albedo (e.g. 2048×2048 alpha vs 1024×1024 albedo).
    if alpha_img.size != albedo_img.size:
        alpha_img = alpha_img.resize(albedo_img.size, Image.Resampling.BILINEAR)

    albedo_rgba = albedo_img.convert("RGBA")
    alpha_rgba = alpha_img.convert("RGBA")

    rgb = np.asarray(albedo_rgba, dtype=np.float32)[..., :3]  # H, W, 3
    alpha_arr = np.asarray(alpha_rgba, dtype=np.float32)  # H, W, 4

    alpha_channel = alpha_arr[..., channel]

    tint_r, tint_g, tint_b, tint_a = p.albedo_tint
    rgb[..., 0] *= tint_r
    rgb[..., 1] *= tint_g
    rgb[..., 2] *= tint_b
    alpha = alpha_channel * tint_a

    rgba = np.empty((rgb.shape[0], rgb.shape[1], 4), dtype=np.uint8)
    rgba[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    rgba[..., 3] = np.clip(alpha, 0, 255).astype(np.uint8)
    return Image.fromarray(rgba, mode="RGBA")
