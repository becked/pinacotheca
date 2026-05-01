"""Resolve a terrain biome (e.g. TERRAIN_TEMPERATE) to its in-game ground
prefab + composed diffuse texture, for use as the bottom layer of layered
capital and urban renders.

The chain is the same one already documented in `asset_index.py`:

    terrain.xml:        TERRAIN_TEMPERATE → aeHeightAsset[HEIGHT_FLAT]
                                          → ASSET_VARIATION_TILE_TEMPERATE_FLAT
    assetVariation.xml: ASSET_VARIATION_TILE_TEMPERATE_FLAT
                                          → aiRandomAssets weighted candidates
                                          → ASSET_TERRAIN_TILE_TEMPERATE_FLAT_01 (highest weight)
    asset.xml:          ASSET_TERRAIN_TILE_TEMPERATE_FLAT_01
                                          → Prefabs/Terrain/TilePlains_01

The terrain tile prefab is itself a `TerrainTexturePVTSplat` plane —
`MeshRenderer.m_Materials` is empty, the in-game terrain shader provides
the visual at runtime via the splat MonoBehaviour's `albedoMap` /
`alphaMap` fields. We treat it identically to a per-nation PVT plane:
parse the splat, compose `albedo × alpha`, render as a hex-shaped quad.

Result is cached at module level — the same biome base is used for every
capital + urban render in a given extraction run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from pinacotheca.asset_index import (
    ASSET_FILES,
    ASSET_VARIATION_FILES,
    TERRAIN_FILES,
    _build_asset_index,
    _build_variation_index,
    _entry_text,
    _load_entries,
)
from pinacotheca.prefab import find_root_gameobject
from pinacotheca.pvt_splats import (
    PvtPlanePart,
    compose_pvt_texture,
    find_pvt_splats_in_prefab,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BiomeBase:
    """The resolved ground splat plane + composed diffuse for one terrain biome.

    `plane` is the PVT splat plane parsed from the biome's flat-tile prefab
    (e.g. TilePlains_01 for TERRAIN_TEMPERATE). It carries the plane's
    MeshFilter mesh + world matrix, the parsed splat fields, and the host
    GameObject name. `diffuse` is the pre-composed `albedo × alpha` RGBA
    image (e.g. Grass_Tile_01_basecolor × Hex_Mask), so the renderer can
    bind it as a single texture without re-running the compositor.
    """

    plane: PvtPlanePart
    diffuse: Image.Image
    prefab_name: str  # e.g. "TilePlains_01" — for diagnostics
    terrain_z_type: str  # e.g. "TERRAIN_TEMPERATE"


_BASE_CACHE: dict[str, BiomeBase] = {}


def _resolve_flat_prefab_name(xml_dir: Path, terrain_z_type: str) -> str:
    """Walk the XML chain from `terrain_z_type` (HEIGHT_FLAT) to a prefab name.

    Raises RuntimeError on any chain miss — the chain has been verified to
    resolve for every base-game terrain biome and we want loud failures
    rather than silent fallbacks.
    """
    terrain_entries = _load_entries(xml_dir, TERRAIN_FILES)
    variation_z: str | None = None
    for entry in terrain_entries:
        if _entry_text(entry, "zType") != terrain_z_type:
            continue
        height_root = entry.find("aeHeightAsset")
        if height_root is None:
            raise RuntimeError(f"{terrain_z_type}: <aeHeightAsset> missing in terrain.xml")
        for pair in height_root.findall("Pair"):
            if _entry_text(pair, "zIndex") == "HEIGHT_FLAT":
                variation_z = _entry_text(pair, "zValue")
                break
        break
    if variation_z is None:
        raise RuntimeError(f"{terrain_z_type}: HEIGHT_FLAT pair missing in <aeHeightAsset>")

    variations = _build_variation_index(_load_entries(xml_dir, ASSET_VARIATION_FILES))
    variation = variations.get(variation_z)
    if variation is None:
        raise RuntimeError(f"{terrain_z_type}: AssetVariation {variation_z} not found")
    best_asset_z, _best_weight = max(variation.candidates, key=lambda c: c[1])

    assets = _build_asset_index(_load_entries(xml_dir, ASSET_FILES))
    prefab = assets.get(best_asset_z)
    if not prefab:
        raise RuntimeError(f"{terrain_z_type}: Asset {best_asset_z} did not resolve to a prefab")
    return prefab


def load_biome_base_from_prefab(
    env: Any,
    prefab_name: str,
    *,
    terrain_z_type: str = "",
) -> BiomeBase:
    """Load the biome base directly from a prefab name (no XML chain walk).

    For callers that already know the prefab — e.g. ``terrain_index`` has
    walked the chain across every (biome, height) tile and hands the
    resolved prefab name in. ``terrain_z_type`` is a free-form label used
    only for diagnostics; the cache is keyed on ``prefab_name`` so different
    biomes can coexist.
    """
    cached = _BASE_CACHE.get(prefab_name)
    if cached is not None:
        return cached

    root = find_root_gameobject(env, prefab_name)
    if root is None:
        raise RuntimeError(
            f"{terrain_z_type or prefab_name}: prefab {prefab_name!r} not found in the asset bundle"
        )
    planes = find_pvt_splats_in_prefab(root)
    if not planes:
        raise RuntimeError(
            f"{terrain_z_type or prefab_name}: prefab {prefab_name!r} "
            "has no TerrainTexturePVTSplat plane"
        )
    if len(planes) > 1:
        logger.warning(
            "%s: prefab %r has %d PVT planes; using the first",
            terrain_z_type or prefab_name,
            prefab_name,
            len(planes),
        )
    plane = planes[0]
    diffuse = compose_pvt_texture(env, plane)
    if diffuse is None:
        raise RuntimeError(
            f"{terrain_z_type or prefab_name}: failed to compose albedo×alpha for {prefab_name!r}"
        )

    base = BiomeBase(
        plane=plane,
        diffuse=diffuse,
        prefab_name=prefab_name,
        terrain_z_type=terrain_z_type or prefab_name,
    )
    _BASE_CACHE[prefab_name] = base
    return base


def load_biome_base(
    env: Any,
    xml_dir: Path,
    terrain_z_type: str = "TERRAIN_TEMPERATE",
) -> BiomeBase:
    """Resolve and load the biome base for `terrain_z_type`.

    Walks terrain.xml → assetVariation.xml → asset.xml to find the prefab,
    then locates the prefab's TerrainTexturePVTSplat plane (every terrain
    flat-tile prefab has exactly one) and pre-composes its albedo × alpha.
    Result is cached so repeated calls in the same extraction run are O(1).
    """
    cached = _BASE_CACHE.get(terrain_z_type)
    if cached is not None:
        return cached

    prefab_name = _resolve_flat_prefab_name(xml_dir, terrain_z_type)
    base = load_biome_base_from_prefab(env, prefab_name, terrain_z_type=terrain_z_type)
    _BASE_CACHE[terrain_z_type] = base
    return base
