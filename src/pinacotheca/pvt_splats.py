"""TerrainTexturePVTSplat / TerrainHeightSplat binary parsers, prefab walker,
and per-plane albedo×alpha texture compositor.

Old World authors per-nation ground decoration (Egyptian sand roads, Greek
mosaic, etc.) as `TerrainTexturePVTSplat` MonoBehaviours attached to flat
Quad/Plane meshes inside each capital/urban prefab. At runtime the game's
`TerrainTextureRenderer` bakes them into per-cell terrain textures via an
orthographic top-down camera; for our offline icon path we render each
plane as its own textured quad and composite them in PIL.

The MonoBehaviour body has no embedded TypeTree, so we hand-parse the
binary against the field layout from `decompiled/Assembly-CSharp/
TerrainTexturePVTSplat.cs` and `TerrainHeightSplat.cs`. Both end with a
body-size assertion that fails loudly if the layout drifts.

Mirrors `clutter_transforms.py` style and reuses its Unity-binary helpers.
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
    Reader,
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
    """Parsed body of a TerrainTexturePVTSplat MonoBehaviour.

    Field order matches the binary layout (TerrainSplatBase.sortingOffset
    first, then TerrainTexturePVTSplat-derived fields in declaration order).
    Body length is 180 bytes after the 32-byte MonoBehaviour header.
    """

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
    """Parsed body of a TerrainHeightSplat MonoBehaviour.

    Body length is 64 bytes after the 32-byte MonoBehaviour header (plus the
    4-byte sortingOffset inherited from TerrainSplatBase).
    """

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
# Binary parsers
# ============================================================


_MB_HEADER_SIZE = 32  # m_GameObject(12) + m_Enabled aligned(4) + m_Script(12) + m_Name length-0(4)


def parse_pvt_splat(raw: bytes) -> PVTSplatFields:
    """Hand-parse a TerrainTexturePVTSplat MonoBehaviour body.

    Asserts at end-of-parse that the consumed byte count matches the body
    length. A drift between this layout and the asset bundle's actual
    layout (e.g. a future game patch adding a [SerializeField]) fails
    loudly with a clear delta rather than returning silently corrupted
    data.
    """
    r = Reader(raw, offset=_MB_HEADER_SIZE)

    sorting_offset = r.read_int32()
    pack_in_atlas = r.read_bool_aligned()
    albedo_atlas = r.read_pptr()
    alpha_atlas = r.read_pptr()
    normal_metalic_roughness_atlas = r.read_pptr()
    use_simple_mode = r.read_bool_aligned()
    material = r.read_pptr()
    material_use_world_uvs = r.read_bool_aligned()
    material_tiling = r.read_float()
    albedo_map = r.read_pptr()
    normal_map = r.read_pptr()
    metallic_map = r.read_pptr()
    roughness_map = r.read_pptr()
    alpha_map = r.read_pptr()
    alpha_map_channel = r.read_int32()
    albedo_tint = (r.read_float(), r.read_float(), r.read_float(), r.read_float())
    normal_map_intensity = r.read_float()
    metallic = r.read_float()
    roughness = r.read_float()
    atlas_index = r.read_int32()
    texture_array_indices = (
        r.read_float(),
        r.read_float(),
        r.read_float(),
        r.read_float(),
    )

    if r.pos != len(raw):
        raise ValueError(
            f"TerrainTexturePVTSplat parse consumed {r.pos} bytes but body is {len(raw)} "
            f"(delta={r.pos - len(raw)}). Field layout may have drifted."
        )

    return PVTSplatFields(
        sorting_offset=sorting_offset,
        pack_in_atlas=pack_in_atlas,
        albedo_atlas=albedo_atlas,
        alpha_atlas=alpha_atlas,
        normal_metalic_roughness_atlas=normal_metalic_roughness_atlas,
        use_simple_mode=use_simple_mode,
        material=material,
        material_use_world_uvs=material_use_world_uvs,
        material_tiling=material_tiling,
        albedo_map=albedo_map,
        normal_map=normal_map,
        metallic_map=metallic_map,
        roughness_map=roughness_map,
        alpha_map=alpha_map,
        alpha_map_channel=alpha_map_channel,
        albedo_tint=albedo_tint,
        normal_map_intensity=normal_map_intensity,
        metallic=metallic,
        roughness=roughness,
        atlas_index=atlas_index,
        texture_array_indices=texture_array_indices,
    )


def parse_height_splat(raw: bytes) -> HeightSplatFields:
    """Hand-parse a TerrainHeightSplat MonoBehaviour body.

    Same body-size assertion as `parse_pvt_splat`. We don't render height
    splats but we parse them as a side-effect drift check — callers may
    pass any TerrainHeightSplat encountered during the prefab walk.
    """
    r = Reader(raw, offset=_MB_HEADER_SIZE)

    sorting_offset = r.read_int32()
    use_simple_mode = r.read_bool_aligned()
    material = r.read_pptr()
    override_world_uv = r.read_bool_aligned()
    intensity = r.read_float()
    tiling = r.read_float()
    rgb_heightmap_middle = r.read_float()
    alphamap_scale_bias = (r.read_float(), r.read_float())
    rgb_heightmap = r.read_pptr()
    heightmap = r.read_pptr()

    if r.pos != len(raw):
        raise ValueError(
            f"TerrainHeightSplat parse consumed {r.pos} bytes but body is {len(raw)} "
            f"(delta={r.pos - len(raw)}). Field layout may have drifted."
        )

    return HeightSplatFields(
        sorting_offset=sorting_offset,
        use_simple_mode=use_simple_mode,
        material=material,
        override_world_uv=override_world_uv,
        intensity=intensity,
        tiling=tiling,
        rgb_heightmap_middle=rgb_heightmap_middle,
        alphamap_scale_bias=alphamap_scale_bias,
        rgb_heightmap=rgb_heightmap,
        heightmap=heightmap,
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
                    raw = r.get_raw_data()
                except Exception as e:
                    logger.warning("TerrainTexturePVTSplat get_raw_data failed: %s", e)
                    continue
                pvt_parsed = parse_pvt_splat(raw)
            elif cls == "TerrainHeightSplat":
                try:
                    raw = r.get_raw_data()
                except Exception as e:
                    logger.warning("TerrainHeightSplat get_raw_data failed: %s", e)
                    continue
                # Parse for drift detection; result is discarded.
                parse_height_splat(raw)

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


def compose_pvt_texture(env: Any, plane: PvtPlanePart) -> Image.Image | None:
    """Compose a single RGBA texture for one PVT plane: albedo × alpha tint.

    Resolves the parsed albedo_map and alpha_map PPtrs, decodes both, and
    produces an RGBA PIL image where:
      out.rgb = albedo.rgb * tint.rgb
      out.a   = alpha[channel] * tint.a

    Channel selection follows the parsed `alpha_map_channel` int against
    the C# `ColorChannel` enum (verified `decompiled/Assembly-CSharp/
    ColorChannel.cs`: 0=R, 1=G, 2=B, 3=A). `material_tiling` is intentionally
    not honored at this stage — mesh UVs already encode the authored layout.

    Returns None (and logs a warning) if either texture PPtr is null,
    fails to resolve, or fails to decode. The renderer's alpha-cutout
    fragment shader (alpha < 0.5 discard) handles the transparent regions
    in the final composite.
    """
    p = plane.parsed
    if p.albedo_map.is_null():
        logger.warning("PVT plane %r has null albedo_map; skipping", plane.host_go_name)
        return None
    if p.alpha_map.is_null():
        logger.warning("PVT plane %r has null alpha_map; skipping", plane.host_go_name)
        return None

    albedo_reader = _resolve_pptr_to_reader(env, p.albedo_map)
    if albedo_reader is None:
        logger.warning("PVT plane %r albedo_map did not resolve", plane.host_go_name)
        return None
    alpha_reader = _resolve_pptr_to_reader(env, p.alpha_map)
    if alpha_reader is None:
        logger.warning("PVT plane %r alpha_map did not resolve", plane.host_go_name)
        return None

    try:
        albedo_tex = albedo_reader.parse_as_object()
        alpha_tex = alpha_reader.parse_as_object()
    except Exception as e:
        logger.warning("PVT plane %r texture parse failed: %s", plane.host_go_name, e)
        return None

    albedo_img = _decode_texture(albedo_tex)
    if albedo_img is None:
        logger.warning("PVT plane %r albedo decode failed", plane.host_go_name)
        return None
    alpha_img = _decode_texture(alpha_tex)
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

    channel = max(0, min(3, int(p.alpha_map_channel)))
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
