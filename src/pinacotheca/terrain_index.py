"""XML-driven discovery of (biome, height) → terrain prefab mappings.

The game's terrain XML chain is

    terrain.xml:           TERRAIN_X × aeHeightAsset[HEIGHT_Y]
                                    → ASSET_VARIATION_TILE_X_Y
    assetVariation.xml:    ASSET_VARIATION_TILE_X_Y
                                    → SingleAsset / aiRandomAssets
                                    → ASSET_TERRAIN_TILE_X_Y_NN
    asset.xml:             ASSET_TERRAIN_TILE_X_Y_NN
                                    → Prefabs/Terrain/...

Two wrinkles drive the resolution rules below:

1. ``HEIGHT_MOUNTAIN`` and ``HEIGHT_VOLCANO`` in ``terrain.xml`` point back
   to the biome's FLAT variation — the chain doesn't carry a per-biome
   mountain/volcano prefab. The single-hex ``TileMountain`` and
   ``TileVolcano_1`` mesh prefabs live behind the well-known variations
   ``ASSET_VARIATION_TILE_MOUNTAIN_1`` and ``ASSET_VARIATION_TILE_VOLCANO_1``
   (the 2/3/4/7-hex range pieces are stamped multi-hex by the runtime; we
   don't render those).

2. ``TERRAIN_URBAN``'s HEIGHT_HILL pair points at the same variation as
   HEIGHT_FLAT, so the visual is identical — we dedupe and emit only
   URBAN_FLAT.

This module has no UnityPy dependency; it's pure-Python XML parsing.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pinacotheca.asset_index import (
    ASSET_FILES,
    ASSET_VARIATION_FILES,
    TERRAIN_FILES,
    _build_asset_index,
    _build_variation_index,
    _entry_text,
    _load_entries,
)

logger = logging.getLogger(__name__)


# Single-hex feature variations resolved outside the (biome, height) chain.
# Verified present in the base-game ``assetVariation.xml`` with
# ``SingleAsset`` pointing at ``ASSET_TERRAIN_TILE_MOUNTAIN_1`` /
# ``ASSET_TERRAIN_TILE_VOLCANO_1``, which themselves point at
# ``Prefabs/Terrain/Mountains/TileMountain`` and
# ``Prefabs/Terrain/Volcanos/TileVolcano_1`` respectively.
MOUNTAIN_VARIATION = "ASSET_VARIATION_TILE_MOUNTAIN_1"
VOLCANO_VARIATION = "ASSET_VARIATION_TILE_VOLCANO_1"

# Land biome heights we emit, in canonical order. URBAN doesn't list
# MOUNTAIN/VOLCANO in terrain.xml so those iterations are no-ops for it.
LAND_HEIGHTS: tuple[str, ...] = ("FLAT", "HILL", "MOUNTAIN", "VOLCANO")


@dataclass(frozen=True)
class TerrainTile:
    """One renderable (biome, height) combination.

    Exactly one of (ground_prefab+feature_prefab) or water_prefab is set:

    - Land biomes (TEMPERATE, LUSH, ARID, SAND, TUNDRA, MARSH, URBAN):
      ``ground_prefab`` is the biome's FLAT PVT plane (e.g. TilePlains_01).
      ``feature_prefab`` is ``None`` for FLAT, the biome's hill mesh for
      HILL, the shared TileMountain mesh for MOUNTAIN, and TileVolcano_1
      for VOLCANO.
    - WATER biome: ``water_prefab`` is TileCoast / TileOcean / TileLake;
      ``ground_prefab`` and ``feature_prefab`` are ``None``.

    ``output_name`` is the canonical filename stem (without extension or
    directory): ``TERRAIN_3D_<BIOME>_<HEIGHT>``. Goes in
    ``extracted/sprites/terrains/``.
    """

    biome: str  # "TEMPERATE", "LUSH", "ARID", "SAND", "TUNDRA", "MARSH", "URBAN", "WATER"
    height: str  # "FLAT", "HILL", "MOUNTAIN", "VOLCANO", "COAST", "OCEAN", "LAKE"
    output_name: str  # "TERRAIN_3D_TEMPERATE_HILL"
    ground_prefab: str | None
    feature_prefab: str | None
    water_prefab: str | None


def _resolve_variation(
    variation_z: str | None,
    variations: Mapping[str, object],
    assets: Mapping[str, str],
) -> str | None:
    """Resolve ``variation_z`` → highest-weighted asset → prefab name.

    Mirrors the rule used by every other loader in ``asset_index`` (max by
    weight, ties broken by document order). Returns ``None`` if the chain
    breaks at any point or ``variation_z`` is itself None.
    """
    if variation_z is None:
        return None
    variation = variations.get(variation_z)
    if variation is None:
        return None
    candidates = getattr(variation, "candidates", ())
    if not candidates:
        return None
    best_asset_z, _best_weight = max(candidates, key=lambda c: c[1])
    return assets.get(best_asset_z)


def _height_to_variation(entry: ET.Element) -> dict[str, str]:
    """Read a terrain.xml entry's ``aeHeightAsset`` block.

    Returns a ``{HEIGHT_X: ASSET_VARIATION_X}`` map. Empty if the block is
    missing or has no resolvable pairs.
    """
    out: dict[str, str] = {}
    height_root = entry.find("aeHeightAsset")
    if height_root is None:
        return out
    for pair in height_root.findall("Pair"):
        h = _entry_text(pair, "zIndex")
        v = _entry_text(pair, "zValue")
        if h and v:
            out[h] = v
    return out


def load_terrain_tiles(xml_dir: Path) -> list[TerrainTile]:
    """Walk ``terrain.xml → assetVariation.xml → asset.xml`` and return one
    ``TerrainTile`` per renderable (biome, height) combination.

    Output set:

    - 6 land biomes × 4 heights = 24 (TEMPERATE / LUSH / ARID / SAND /
      TUNDRA / MARSH × FLAT / HILL / MOUNTAIN / VOLCANO)
    - URBAN × 1 (FLAT — URBAN/HILL collapses to URBAN/FLAT and is skipped)
    - WATER × 3 (COAST, OCEAN, LAKE)

    = 28 tiles total.

    Tiles whose chain doesn't resolve at any stage are dropped with a
    warning log — we'd rather emit a smaller-but-correct set than 404 PNGs.
    Returns an empty list if ``xml_dir`` doesn't exist.
    """
    if not xml_dir.exists():
        logger.warning("XML directory not found: %s", xml_dir)
        return []

    terrain_entries = _load_entries(xml_dir, TERRAIN_FILES)
    variations = _build_variation_index(_load_entries(xml_dir, ASSET_VARIATION_FILES))
    assets = _build_asset_index(_load_entries(xml_dir, ASSET_FILES))

    mountain_prefab = _resolve_variation(MOUNTAIN_VARIATION, variations, assets)
    volcano_prefab = _resolve_variation(VOLCANO_VARIATION, variations, assets)
    if mountain_prefab is None:
        logger.warning("MOUNTAIN feature variation %s did not resolve", MOUNTAIN_VARIATION)
    if volcano_prefab is None:
        logger.warning("VOLCANO feature variation %s did not resolve", VOLCANO_VARIATION)

    out: list[TerrainTile] = []
    seen_outputs: set[str] = set()

    def _emit(tile: TerrainTile) -> None:
        if tile.output_name in seen_outputs:
            return
        seen_outputs.add(tile.output_name)
        out.append(tile)

    for entry in terrain_entries:
        biome_z = _entry_text(entry, "zType")
        if not biome_z or not biome_z.startswith("TERRAIN_"):
            continue
        biome = biome_z.removeprefix("TERRAIN_")
        height_to_var = _height_to_variation(entry)

        if biome == "WATER":
            # Each of COAST / OCEAN / LAKE is a distinct prefab; no biome
            # ground underneath.
            for h_z, water_var in height_to_var.items():
                height = h_z.removeprefix("HEIGHT_")
                water_prefab = _resolve_variation(water_var, variations, assets)
                if water_prefab is None:
                    logger.warning("WATER × %s: chain failed (variation=%s)", height, water_var)
                    continue
                _emit(
                    TerrainTile(
                        biome=biome,
                        height=height,
                        output_name=f"TERRAIN_3D_{biome}_{height}",
                        ground_prefab=None,
                        feature_prefab=None,
                        water_prefab=water_prefab,
                    )
                )
            continue

        # Land biome: resolve the FLAT variation once (used as ground for
        # every height we emit for this biome).
        flat_var = height_to_var.get("HEIGHT_FLAT")
        ground_prefab = _resolve_variation(flat_var, variations, assets) if flat_var else None
        if ground_prefab is None:
            logger.warning("%s: FLAT ground unresolvable; skipping all heights", biome)
            continue

        for h in LAND_HEIGHTS:
            h_z = f"HEIGHT_{h}"
            v_z_opt = height_to_var.get(h_z)
            if v_z_opt is None:
                continue
            v_z: str = v_z_opt
            feature_prefab: str | None
            if h == "FLAT":
                feature_prefab = None
            elif h == "HILL":
                # When HILL points at the same variation as FLAT (URBAN
                # behaves this way), the prefab is identical — skip the dupe.
                if v_z == flat_var:
                    continue
                feature_prefab = _resolve_variation(v_z, variations, assets)
                if feature_prefab is None:
                    logger.warning("%s × HILL: feature unresolvable (variation=%s)", biome, v_z)
                    continue
            elif h == "MOUNTAIN":
                if mountain_prefab is None:
                    continue
                feature_prefab = mountain_prefab
            elif h == "VOLCANO":
                if volcano_prefab is None:
                    continue
                feature_prefab = volcano_prefab
            else:
                continue

            _emit(
                TerrainTile(
                    biome=biome,
                    height=h,
                    output_name=f"TERRAIN_3D_{biome}_{h}",
                    ground_prefab=ground_prefab,
                    feature_prefab=feature_prefab,
                    water_prefab=None,
                )
            )

    if logger.isEnabledFor(logging.INFO):
        by_biome: dict[str, int] = {}
        for tile in out:
            by_biome[tile.biome] = by_biome.get(tile.biome, 0) + 1
        logger.info(
            "load_terrain_tiles: %d tiles (%s)",
            len(out),
            ", ".join(f"{b}={n}" for b, n in sorted(by_biome.items())),
        )

    return out
