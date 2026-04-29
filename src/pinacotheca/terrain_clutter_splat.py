"""TerrainClutterSplat binary parser, prefab walker, and per-channel mask
texture compositor.

When the game places an improvement on a city's urban tile, the improvement
prefab's `Clutter-Mask` child carries a `TerrainClutterSplat` MonoBehaviour.
At runtime that splat plane bakes mask values into per-tile clutter channels
(Trees / MinorBuildings / MajorBuildings); each piece of urban background
clutter then samples the mask at its world position for its own
`TerrainClutterType` channel and is probabilistically culled
(`channel_value > RandomStruct(0).NextFloat()` → hide). See
`decompiled/Assembly-CSharp/TerrainClutterSplat.cs`,
`ClutterMaskable.cs`, and `ClutterTransformsBackgroundData.cs:158-162`.

For our offline composites we replicate that flow:
  1. Parse each `TerrainClutterSplat` body (`parse_terrain_clutter_splat`).
  2. Walk the improvement prefab to find every plane
     (`find_terrain_clutter_splats_in_prefab`).
  3. Compose a 3-channel mask texture per plane where R/G/B encode the
     channel-tinted intensity for Trees/MinorBuildings/MajorBuildings
     (`compose_clutter_mask_texture`); zero where the corresponding
     `clear*` flag is False.
  4. The cull pass (in `clutter_culling.py`) projects each clutter
     instance's world XZ into mask UV, samples the channel for its
     resolved `TerrainClutterType`, and applies the random-compare rule.

The MonoBehaviour body has no embedded TypeTree, so we hand-parse the
binary against the field layout from `TerrainClutterSplat.cs`. Verified
on Library + Palace prefabs: body is exactly 72 bytes (Unity serializes
each public bool as 1 byte then aligns to 4, so the three `clear*` flags
contribute 12 bytes). End-of-parse assertion fails loudly if a future
patch reorders fields.

Mirrors `pvt_splats.py` structure and reuses its Unity-binary helpers.
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
class TerrainClutterSplatFields:
    """Parsed body of a TerrainClutterSplat MonoBehaviour.

    Field order matches the binary layout: `TerrainSplatBase.sortingOffset`
    first, then the `TerrainClutterSplat`-derived fields in C# declaration
    order. Body length is 72 bytes after the 32-byte MonoBehaviour header.
    """

    sorting_offset: int
    use_simple_mode: bool
    material: PPtr
    cluttermask: PPtr
    override_alphamap_use_world_uvs_on: bool
    clutter_mask_channel: int  # ColorChannel enum: 0=R, 1=G, 2=B, 3=A
    alphamask: PPtr
    clear_trees: bool
    clear_minor_buildings: bool
    clear_major_buildings: bool
    clutter_intensity: float
    tiling: float


@dataclass(frozen=True)
class ClutterMaskPart:
    """One TerrainClutterSplat plane found inside a prefab tree.

    `mesh_obj` is the plane GameObject's MeshFilter mesh PPtr (typically a
    Unity built-in Quad). `world_matrix` is the plane's full accumulated TRS
    so the cull pass can project clutter world XZ into mask UV.
    """

    parsed: TerrainClutterSplatFields
    mesh_obj: Any  # MeshFilter m_Mesh PPtr — UnityPy native form
    world_matrix: NDArray[np.float64]
    materials: list[Any]  # MeshRenderer m_Materials, for diagnostics
    host_go_name: str


# ============================================================
# Binary parser
# ============================================================


_MB_HEADER_SIZE = 32  # m_GameObject(12) + m_Enabled aligned(4) + m_Script(12) + m_Name length-0(4)
_BODY_SIZE = 72


def parse_terrain_clutter_splat(raw: bytes) -> TerrainClutterSplatFields:
    """Hand-parse a TerrainClutterSplat MonoBehaviour body.

    Asserts at end-of-parse that the consumed byte count matches the
    expected body length. A drift between this layout and the asset
    bundle's actual layout (e.g. a future game patch adding a
    [SerializeField]) fails loudly with a clear delta rather than
    returning silently corrupted data.
    """
    r = Reader(raw, offset=_MB_HEADER_SIZE)

    sorting_offset = r.read_int32()
    use_simple_mode = r.read_bool_aligned()
    material = r.read_pptr()
    cluttermask = r.read_pptr()
    override_alphamap_use_world_uvs_on = r.read_bool_aligned()
    clutter_mask_channel = r.read_int32()
    alphamask = r.read_pptr()
    clear_trees = r.read_bool_aligned()
    clear_minor_buildings = r.read_bool_aligned()
    clear_major_buildings = r.read_bool_aligned()
    clutter_intensity = r.read_float()
    tiling = r.read_float()

    consumed = r.pos - _MB_HEADER_SIZE
    if consumed != _BODY_SIZE:
        raise ValueError(
            f"TerrainClutterSplat parse consumed {consumed} body bytes but expected "
            f"{_BODY_SIZE} (delta={consumed - _BODY_SIZE}). Field layout may have drifted."
        )
    if r.pos != len(raw):
        raise ValueError(
            f"TerrainClutterSplat raw length {len(raw)} does not match header+body "
            f"({_MB_HEADER_SIZE} + {_BODY_SIZE} = {_MB_HEADER_SIZE + _BODY_SIZE}); "
            f"reader stopped at {r.pos}."
        )

    return TerrainClutterSplatFields(
        sorting_offset=sorting_offset,
        use_simple_mode=use_simple_mode,
        material=material,
        cluttermask=cluttermask,
        override_alphamap_use_world_uvs_on=override_alphamap_use_world_uvs_on,
        clutter_mask_channel=clutter_mask_channel,
        alphamask=alphamask,
        clear_trees=clear_trees,
        clear_minor_buildings=clear_minor_buildings,
        clear_major_buildings=clear_major_buildings,
        clutter_intensity=clutter_intensity,
        tiling=tiling,
    )


# ============================================================
# Prefab-tree walker
# ============================================================


def find_terrain_clutter_splats_in_prefab(root_go: Any) -> list[ClutterMaskPart]:
    """Descend the prefab tree, find every TerrainClutterSplat plane,
    pair each with its host GameObject's MeshFilter mesh + world matrix.

    Find by script class, not GameObject name — improvement authors don't
    consistently name the host (commonly `Clutter-Mask`, but not enforced).
    """
    found: list[ClutterMaskPart] = []
    for go, world in _walk_prefab_with_world(root_go):
        parsed: TerrainClutterSplatFields | None = None
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
            if cls != "TerrainClutterSplat":
                continue
            try:
                raw = r.get_raw_data()
            except Exception as e:
                logger.warning("TerrainClutterSplat get_raw_data failed: %s", e)
                continue
            try:
                parsed = parse_terrain_clutter_splat(raw)
            except Exception as e:
                logger.warning(
                    "TerrainClutterSplat parse failed on %r: %s",
                    getattr(go, "m_Name", "?"),
                    e,
                )
                parsed = None

        if parsed is None:
            continue

        mf = _component_by_type(go, "MeshFilter")
        if mf is None:
            logger.warning(
                "TerrainClutterSplat on %r has no MeshFilter sibling; skipping",
                getattr(go, "m_Name", "?"),
            )
            continue
        mf_mesh = getattr(mf, "m_Mesh", None)
        if mf_mesh is None or not bool(mf_mesh):
            logger.warning(
                "TerrainClutterSplat on %r has MeshFilter with null mesh; skipping",
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
            ClutterMaskPart(
                parsed=parsed,
                mesh_obj=mf_mesh,
                world_matrix=world.copy(),
                materials=materials,
                host_go_name=str(getattr(go, "m_Name", "?")),
            )
        )
    return found


# ============================================================
# Per-channel mask texture compositor
# ============================================================


def compose_clutter_mask_texture(env: Any, plane: ClutterMaskPart) -> Image.Image | None:
    """Compose a 3-channel mask image for one TerrainClutterSplat plane.

    Output channel layout matches `TerrainClutterType` enum ordering:

        R = mask_value if clear_trees           else 0
        G = mask_value if clear_minor_buildings else 0
        B = mask_value if clear_major_buildings else 0

    where `mask_value = cluttermask[clutter_mask_channel] * clutter_intensity`,
    with all values in [0, 1] saturated to [0, 255].

    The cull pass samples this image at each clutter instance's projected
    UV: `out[v, u, clutter_type]` is the per-instance hide-probability
    (compared against `RandomStruct.NextFloat()`).

    Returns None (and logs a warning) if the cluttermask PPtr is null,
    fails to resolve, or fails to decode.
    """
    p = plane.parsed
    if p.cluttermask.is_null():
        logger.warning(
            "TerrainClutterSplat %r has null cluttermask; skipping",
            plane.host_go_name,
        )
        return None

    cm_reader = _resolve_pptr_to_reader(env, p.cluttermask)
    if cm_reader is None:
        logger.warning(
            "TerrainClutterSplat %r cluttermask did not resolve",
            plane.host_go_name,
        )
        return None

    try:
        cm_tex = cm_reader.parse_as_object()
    except Exception as e:
        logger.warning(
            "TerrainClutterSplat %r cluttermask parse failed: %s",
            plane.host_go_name,
            e,
        )
        return None

    cm_img = _decode_texture(cm_tex)
    if cm_img is None:
        logger.warning(
            "TerrainClutterSplat %r cluttermask decode failed",
            plane.host_go_name,
        )
        return None

    rgba = cm_img.convert("RGBA")
    arr = np.asarray(rgba, dtype=np.float32)  # H, W, 4 in [0, 255]

    channel = max(0, min(3, int(p.clutter_mask_channel)))
    mask_value = arr[..., channel] * float(p.clutter_intensity)  # in [0, 255 * intensity]
    mask_value = np.clip(mask_value, 0.0, 255.0)

    h, w = mask_value.shape
    out = np.zeros((h, w, 3), dtype=np.uint8)
    if p.clear_trees:
        out[..., 0] = mask_value.astype(np.uint8)
    if p.clear_minor_buildings:
        out[..., 1] = mask_value.astype(np.uint8)
    if p.clear_major_buildings:
        out[..., 2] = mask_value.astype(np.uint8)

    return Image.fromarray(out, mode="RGB")
