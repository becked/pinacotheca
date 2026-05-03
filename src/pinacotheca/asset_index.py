"""
XML-driven discovery of improvement → prefab mappings.

The game's source of truth for "which mesh represents which improvement"
is a three-XML chain in `Reference/XML/Infos/`:

    improvement.xml:        IMPROVEMENT_X     → AssetVariation: ASSET_VARIATION_IMPROVEMENT_X
    assetVariation.xml:     ASSET_VARIATION_X → SingleAsset: ASSET_IMPROVEMENT_X
                                                (or aiRandomAssets weighted list)
    asset.xml:              ASSET_IMPROVEMENT_X → zAsset: Prefabs/Improvements/Y

The last path component (`Y`) is the GameObject name in the Unity asset
bundle — the value passed to `prefab.find_root_gameobject`.

DLC content lives in sibling files (`assetVariation-eoti.xml`,
`asset-btt.xml`, etc.) that ADD entries — no overrides. We merge all
present files into one big dict per stage of the chain.

This module has no UnityPy dependency; it's pure-Python XML parsing so
the asset chain can be tested independently of Unity assets.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# Files to merge for each stage of the chain. Order is base file first,
# then DLC additions. We tolerate any of them being missing (the game
# install may not have every DLC), but log when one we expect is absent.
IMPROVEMENT_FILES: tuple[str, ...] = (
    "improvement.xml",
    "improvement-event.xml",
)
# Used by `load_urban_renderable_improvements` only — adds the SAP event
# pack, which holds scenario shrines that we filter OUT via the
# `GameContentRequired=EVENTPACK_*` gate. Reading the file lets us see
# (and explicitly exclude) those entries.
URBAN_IMPROVEMENT_FILES: tuple[str, ...] = (
    "improvement.xml",
    "improvement-event.xml",
    "improvement-event-sap.xml",
)

TERRAIN_TARGET_FILES: tuple[str, ...] = ("terrainTarget.xml",)
TERRAIN_URBAN = "TERRAIN_URBAN"

# DynastyPrereq → NationPrereq fallback. Old World ships dynasty-locked
# improvements (so far just Serapis under DYNASTY_PTOLEMY = Ptolemaic
# Egypt). Each entry here translates into "this dynasty's improvement
# renders only on that nation's urban tile". Extend if new dynasty-locked
# urban improvements appear in DLC.
_DYNASTY_TO_NATION: dict[str, str] = {
    "DYNASTY_PTOLEMY": "NATION_EGYPT",
}
RESOURCE_FILES: tuple[str, ...] = (
    "resource.xml",
    "resource-btt.xml",
    "resource-eoti.xml",
    "resource-wd.xml",
)
ASSET_VARIATION_FILES: tuple[str, ...] = (
    "assetVariation.xml",
    "assetVariation-btt.xml",
    "assetVariation-eoti.xml",
    "assetVariation-wd.xml",
)
ASSET_FILES: tuple[str, ...] = (
    "asset.xml",
    "asset-btt.xml",
    "asset-eoti.xml",
    "asset-wd.xml",
)
TERRAIN_FILES: tuple[str, ...] = ("terrain.xml",)


@dataclass(frozen=True)
class ImprovementAsset:
    """One (improvement, prefab) pair resolved through the XML chain.

    `z_icon_name` is the canonical name and what the output filename uses.
    Multiple `z_type`s can share a `z_icon_name` (tier-upgrade chains often
    do — e.g. `IMPROVEMENT_LIBRARY_1` and `IMPROVEMENT_LIBRARY_2` may both
    have `zIconName=IMPROVEMENT_LIBRARY` if the basic-tier and upgraded-tier
    visualize the same way). We dedupe on `z_icon_name`; the first
    `z_type` seen wins.
    """

    z_icon_name: str  # "IMPROVEMENT_LIBRARY" — canonical, used for output filename
    prefab_name: str  # "Library" — last segment of zAsset path; pass to find_root_gameobject
    z_type: str  # "IMPROVEMENT_LIBRARY_1" — the actual XML entry that resolved
    asset_z_type: str  # "ASSET_IMPROVEMENT_LIBRARY_1" — for diagnostics
    weight: int  # 1 for SingleAsset; iValue for aiRandomAssets


def _load_entries(xml_dir: Path, filenames: tuple[str, ...]) -> list[ET.Element]:
    """Concatenate <Entry> children across the listed XML files."""
    entries: list[ET.Element] = []
    for name in filenames:
        path = xml_dir / name
        if not path.exists():
            logger.debug("XML file not present, skipping: %s", path)
            continue
        try:
            tree = ET.parse(path)
        except ET.ParseError as e:
            logger.warning("Failed to parse %s: %s", path, e)
            continue
        root = tree.getroot()
        entries.extend(root.findall("Entry"))
    return entries


def _entry_text(entry: ET.Element, tag: str) -> str | None:
    """Return the stripped text of a child tag, or None if absent/empty."""
    el = entry.find(tag)
    if el is None or el.text is None:
        return None
    text = el.text.strip()
    return text or None


@dataclass(frozen=True)
class _ImprovementEntry:
    z_type: str  # IMPROVEMENT_LIBRARY_1
    z_icon_name: str  # IMPROVEMENT_LIBRARY (often differs from z_type for upgrade tiers)
    asset_variation: str  # ASSET_VARIATION_IMPROVEMENT_LIBRARY_1


def _build_improvement_entries(entries: list[ET.Element]) -> list[_ImprovementEntry]:
    """
    Parse improvement.xml entries with their AssetVariation and zIconName.

    `<zIconName>` is the game's canonical name used for icon lookup —
    multiple `<zType>` entries (upgrade tiers, etc.) often share the same
    `<zIconName>`. When `<zIconName>` is missing we fall back to `<zType>`.
    Skips entries with no AssetVariation (logged at debug).
    """
    out: list[_ImprovementEntry] = []
    for entry in entries:
        z_type = _entry_text(entry, "zType")
        if not z_type:
            continue
        asset_var = _entry_text(entry, "AssetVariation")
        if not asset_var:
            logger.debug("Improvement %s has no AssetVariation; skipping", z_type)
            continue
        z_icon_name = _entry_text(entry, "zIconName") or z_type
        out.append(
            _ImprovementEntry(
                z_type=z_type,
                z_icon_name=z_icon_name,
                asset_variation=asset_var,
            )
        )
    return out


@dataclass(frozen=True)
class _VariationResolution:
    """A resolved AssetVariation: a list of (asset_z_type, weight) candidates.

    For SingleAsset entries the list has one element with weight=1. For
    aiRandomAssets the list mirrors the weighted Pair entries.
    """

    candidates: tuple[tuple[str, int], ...]


def _build_variation_index(entries: list[ET.Element]) -> dict[str, _VariationResolution]:
    """
    Map AssetVariation zType → list of (asset_z_type, weight) candidates.

    Variation may use either `<SingleAsset>` (one fixed asset) or
    `<aiRandomAssets>` (weighted random list of `<Pair>` elements with
    `<zIndex>` + `<iValue>`). Variations with neither are skipped+logged.
    """
    out: dict[str, _VariationResolution] = {}
    for entry in entries:
        z_type = _entry_text(entry, "zType")
        if not z_type:
            continue
        single = _entry_text(entry, "SingleAsset")
        if single:
            out[z_type] = _VariationResolution(candidates=((single, 1),))
            continue
        random_root = entry.find("aiRandomAssets")
        if random_root is not None:
            candidates: list[tuple[str, int]] = []
            for pair in random_root.findall("Pair"):
                z_index = _entry_text(pair, "zIndex")
                i_value_str = _entry_text(pair, "iValue")
                if not z_index:
                    continue
                try:
                    i_value = int(i_value_str) if i_value_str else 1
                except ValueError:
                    i_value = 1
                candidates.append((z_index, i_value))
            if candidates:
                out[z_type] = _VariationResolution(candidates=tuple(candidates))
                continue
        logger.debug("AssetVariation %s has neither SingleAsset nor aiRandomAssets", z_type)
    return out


def _build_asset_index(entries: list[ET.Element]) -> dict[str, str]:
    """
    Map Asset zType → prefab name (the last component of the zAsset path).

    `Prefabs/Improvements/Library` → `Library`.
    `Prefabs/Cities/Maurya/Maurya_Capital` → `Maurya_Capital`.
    Empty/missing zAsset is skipped+logged.
    """
    out: dict[str, str] = {}
    for entry in entries:
        z_type = _entry_text(entry, "zType")
        if not z_type:
            continue
        path = _entry_text(entry, "zAsset")
        if not path:
            continue
        # Last path component, regardless of separator depth
        prefab = path.rsplit("/", 1)[-1]
        if not prefab:
            logger.debug("Asset %s has empty prefab name (zAsset=%r)", z_type, path)
            continue
        out[z_type] = prefab
    return out


@dataclass(frozen=True)
class _ResourceEntry:
    z_type: str  # RESOURCE_ORE
    z_icon_name: str  # RESOURCE_IRON (often differs from z_type — alias to a shared visual)
    asset_variation: str  # ASSET_VARIATION_RESOURCE_ORE


def _build_resource_entries(entries: list[ET.Element]) -> list[_ResourceEntry]:
    """Parse resource.xml entries with their AssetVariation and zIconName.

    Same shape as `_build_improvement_entries`. Resources alias to a
    shared visual via `<zIconName>` (RESOURCE_ORE → RESOURCE_IRON,
    RESOURCE_MARBLE → RESOURCE_STONE) — multiple zTypes may share an
    icon name. When `<zIconName>` is missing we fall back to `<zType>`.
    """
    out: list[_ResourceEntry] = []
    for entry in entries:
        z_type = _entry_text(entry, "zType")
        if not z_type:
            continue
        asset_var = _entry_text(entry, "AssetVariation")
        if not asset_var:
            logger.debug("Resource %s has no AssetVariation; skipping", z_type)
            continue
        z_icon_name = _entry_text(entry, "zIconName") or z_type
        out.append(
            _ResourceEntry(
                z_type=z_type,
                z_icon_name=z_icon_name,
                asset_variation=asset_var,
            )
        )
    return out


def load_resource_assets(xml_dir: Path) -> list[ImprovementAsset]:
    """
    Walk resource.xml → assetVariation.xml → asset.xml and return one
    `ImprovementAsset` per unique resource zIconName.

    Resources are tile-level decorations spawned by `ResourceRenderer.cs`
    independently of improvements. The Pasture *fence* lives in the
    improvement prefab; the herd of horses/sheep on the tile under it
    lives in `Prefabs/Resource/<animal>`. Without this loader those
    resource prefabs aren't extracted.

    Returns the same `ImprovementAsset` shape as `load_improvement_assets`
    so callers can use a single render pipeline. Output filenames built
    from `z_icon_name` (canonical) — the existing dedupe pattern.

    Skips entries whose zType is not in the per-ankh-relevant set is NOT
    done here; we extract every resource the chain resolves and let the
    consumer decide which to use. This mirrors how improvements are
    handled.
    """
    if not xml_dir.exists():
        logger.warning("XML directory not found: %s", xml_dir)
        return []

    resource_entries = _build_resource_entries(_load_entries(xml_dir, RESOURCE_FILES))
    variations = _build_variation_index(_load_entries(xml_dir, ASSET_VARIATION_FILES))
    assets = _build_asset_index(_load_entries(xml_dir, ASSET_FILES))

    seen_icons: set[str] = set()
    out: list[ImprovementAsset] = []
    skipped_no_variation = 0
    skipped_no_asset = 0
    skipped_duplicate_icon = 0

    for entry in resource_entries:
        if entry.z_icon_name in seen_icons:
            skipped_duplicate_icon += 1
            continue
        variation = variations.get(entry.asset_variation)
        if variation is None:
            logger.debug("%s → %s: variation not found", entry.z_type, entry.asset_variation)
            skipped_no_variation += 1
            continue
        best_asset_z, best_weight = max(variation.candidates, key=lambda c: c[1])
        prefab = assets.get(best_asset_z)
        if not prefab:
            logger.debug(
                "%s → %s → %s: asset not found",
                entry.z_type,
                entry.asset_variation,
                best_asset_z,
            )
            skipped_no_asset += 1
            continue
        seen_icons.add(entry.z_icon_name)
        out.append(
            ImprovementAsset(
                z_icon_name=entry.z_icon_name,
                prefab_name=prefab,
                z_type=entry.z_type,
                asset_z_type=best_asset_z,
                weight=best_weight,
            )
        )

    if skipped_no_variation or skipped_no_asset or skipped_duplicate_icon:
        logger.info(
            "load_resource_assets: %d resolved, %d no-variation, %d no-asset, %d duplicate-icon",
            len(out),
            skipped_no_variation,
            skipped_no_asset,
            skipped_duplicate_icon,
        )

    return out


# ============================================================
# Vegetation chain
# ============================================================
#
# Vegetation prefabs (Trees, Jungle, Scrub, ForestCut, JungleCut +
# their charred / charred_minor / hurricane variants) live in the same
# AssetVariation → Asset chain as everything else, but vegetation.xml
# itself only enumerates the six base types (TREES, TREES_CUT, JUNGLE,
# JUNGLE_CUT, SCRUB, SCRUB_CUT). The runtime overrides (charred state,
# hurricane state, per-(terrain, height) variants) are stored as extra
# AssetVariation entries with name suffixes — `_ARID`, `_HILL`,
# `_CHARRED`, `_CHARRED_MINOR`, `_HURRICANE`, `_CUT`. We discover the
# full set by scanning every `ASSET_VARIATION_VEGETATION_*` entry and
# parsing terrain/height/modifier from the suffix.


_VEG_VARIATION_PREFIX = "ASSET_VARIATION_VEGETATION_"
# Possible suffix tokens on a vegetation variation name, listed by the
# slot they occupy (terrain, height, modifier). Order within each tuple
# matters for the suffix parser — longer matches first.
_VEG_TERRAIN_SUFFIXES: tuple[str, ...] = ("ARID",)
_VEG_HEIGHT_SUFFIXES: tuple[str, ...] = ("HILL",)
_VEG_MODIFIER_SUFFIXES: tuple[str, ...] = (
    "CHARRED_MINOR",
    "CHARRED",
    "HURRICANE",
    "CUT_CHARRED",
    "CUT",
)


@dataclass(frozen=True)
class VegetationAsset:
    """One vegetation variant resolved through the AssetVariation chain.

    `output_name` is the canonical filename stem (sans extension or
    directory) that the extractor uses: `VEGETATION_3D_<output_name>.png`.
    For multi-candidate variations (`aiRandomAssets`), `output_name`
    carries a zero-padded `_NN` suffix matching the candidate index, e.g.
    `TREES_01`, `JUNGLE_HILL_HURRICANE_01`. Variations whose candidates
    all resolve to the same prefab are deduped — we emit one PNG per
    unique prefab, indexed by first appearance.

    `terrain_z_type` and `height_z_type` are extracted from the variation
    name suffix (default TEMPERATE / FLAT). The extractor uses them to
    pick the matching biome ground for the layered render. Hill height
    is recorded but rendered on flat ground in v1 — the 3D peak feature
    is deferred (see `terrain_render.py` for the per-(biome, height)
    composition pattern used by terrain tiles).
    """

    output_name: str  # "TREES_01", "JUNGLE_HILL_HURRICANE", "SCRUB_ARID_CHARRED_MINOR"
    prefab_name: str  # "Temperate_Tree_01_Cluster_Impostors" — for find_root_gameobject
    variation_z_type: str  # "ASSET_VARIATION_VEGETATION_TREES" — for diagnostics
    asset_z_type: str  # "ASSET_VEGETATION_TREES" — for diagnostics
    terrain_z_type: str  # "TERRAIN_TEMPERATE", "TERRAIN_ARID"
    height_z_type: str  # "HEIGHT_FLAT", "HEIGHT_HILL"


def _parse_vegetation_suffix(rest: str) -> tuple[str, str]:
    """Extract (terrain_z_type, height_z_type) from a vegetation variation
    name suffix.

    `rest` is the part after `ASSET_VARIATION_VEGETATION_` (e.g.
    `TREES_HILL_CHARRED`). We scan for known tokens delimited by `_`:
    `ARID` → TERRAIN_ARID; `HILL` → HEIGHT_HILL; everything else is
    a vegetation type or a state modifier (CUT, CHARRED, HURRICANE, etc.)
    that doesn't affect the underlying terrain/height. Defaults are
    TEMPERATE + FLAT.
    """
    tokens = rest.split("_")
    terrain = "TERRAIN_TEMPERATE"
    height = "HEIGHT_FLAT"
    if "ARID" in tokens:
        terrain = "TERRAIN_ARID"
    if "HILL" in tokens:
        height = "HEIGHT_HILL"
    return terrain, height


def load_vegetation_assets(xml_dir: Path) -> list[VegetationAsset]:
    """Walk the vegetation slice of the AssetVariation → Asset chain and
    return one `VegetationAsset` per renderable (variation, candidate)
    pair, deduped by prefab name within each variation.

    Discovery is variation-driven, not vegetation.xml-driven: we scan
    every `ASSET_VARIATION_VEGETATION_*` entry, which captures the base
    types AND every charred / hurricane / per-(terrain, height) override.
    `aiRandomAssets` variations expand to one entry per unique prefab,
    each with a `_NN` zero-padded suffix on `output_name`.

    All vegetation lives in the same DLC file lists as improvements
    (`assetVariation-eoti.xml` adds JUNGLE; `asset-eoti.xml` carries
    the jungle prefabs). `vegetation.xml` itself has no DLC siblings —
    EOTI-gated entries (jungle) live in the base file with a
    `<GameContentDisplay>` tag.

    Returns an empty list if `xml_dir` doesn't exist.
    """
    if not xml_dir.exists():
        logger.warning("XML directory not found: %s", xml_dir)
        return []

    variations = _build_variation_index(_load_entries(xml_dir, ASSET_VARIATION_FILES))
    assets = _build_asset_index(_load_entries(xml_dir, ASSET_FILES))

    out: list[VegetationAsset] = []
    skipped_no_asset = 0

    # Sort for deterministic output order across runs.
    veg_variation_keys = sorted(k for k in variations if k.startswith(_VEG_VARIATION_PREFIX))
    for var_z in veg_variation_keys:
        rest = var_z.removeprefix(_VEG_VARIATION_PREFIX)
        terrain_z, height_z = _parse_vegetation_suffix(rest)
        variation = variations[var_z]

        # Dedupe candidates by resolved prefab name within this variation.
        # Several charred variations point all 3 random candidates at the
        # same _02 prefab — emitting 3 identical PNGs is wasteful.
        seen_prefabs: dict[str, int] = {}  # prefab → 1-based index of first appearance
        candidates_with_prefab: list[tuple[str, str, int]] = []  # (asset_z, prefab, idx)
        for asset_z, _weight in variation.candidates:
            prefab = assets.get(asset_z)
            if not prefab:
                skipped_no_asset += 1
                continue
            if prefab in seen_prefabs:
                continue
            idx = len(seen_prefabs) + 1
            seen_prefabs[prefab] = idx
            candidates_with_prefab.append((asset_z, prefab, idx))

        if not candidates_with_prefab:
            continue

        multi = len(candidates_with_prefab) > 1
        for asset_z, prefab, idx in candidates_with_prefab:
            output_name = f"{rest}_{idx:02d}" if multi else rest
            out.append(
                VegetationAsset(
                    output_name=output_name,
                    prefab_name=prefab,
                    variation_z_type=var_z,
                    asset_z_type=asset_z,
                    terrain_z_type=terrain_z,
                    height_z_type=height_z,
                )
            )

    if skipped_no_asset:
        logger.info(
            "load_vegetation_assets: %d resolved, %d candidates with no asset",
            len(out),
            skipped_no_asset,
        )

    return out


def load_urban_assets(xml_dir: Path) -> list[ImprovementAsset]:
    """
    Discover per-nation urban-tile prefabs by scanning asset.xml directly.

    Urban tiles (Greece_Urban, Egypt_Urban, etc.) are referenced from Nation
    info at runtime (`Tile.cs:13029` `infos.nation(eNation).meUrbanAsset`)
    rather than through an AssetVariation wrapper. They appear in `asset.xml`
    as direct entries with `zType` of the form `ASSET_<NATION>_URBAN` and a
    `zAsset` of `Prefabs/Cities/<Nation>/<Nation>_Urban`.

    Returns the same `ImprovementAsset` shape as `load_capital_assets`. The
    canonical name strips the `ASSET_` prefix (`ASSET_GREECE_URBAN` →
    `GREECE_URBAN`) so output filenames are `IMPROVEMENT_3D_<NATION>_URBAN.png`.
    """
    if not xml_dir.exists():
        return []

    out: list[ImprovementAsset] = []
    for entry in _load_entries(xml_dir, ASSET_FILES):
        z_type = _entry_text(entry, "zType")
        if not z_type:
            continue
        # Filter to per-nation urban entries; skip ASSET_URBAN (Primitive
        # generic), ASSET_TERRAIN_URBAN_FLAT (terrain tile, not a nation).
        if not z_type.startswith("ASSET_") or not z_type.endswith("_URBAN"):
            continue
        if z_type in ("ASSET_URBAN", "ASSET_TERRAIN_URBAN_FLAT"):
            continue
        path = _entry_text(entry, "zAsset")
        if not path:
            continue
        prefab = path.rsplit("/", 1)[-1]
        if not prefab:
            continue
        canonical = z_type.removeprefix("ASSET_")
        out.append(
            ImprovementAsset(
                z_icon_name=canonical,
                prefab_name=prefab,
                z_type=z_type,
                asset_z_type=z_type,
                weight=1,
            )
        )
    return out


def load_capital_assets(xml_dir: Path) -> list[ImprovementAsset]:
    """
    Discover nation-capital prefabs by scanning the AssetVariation chain.

    Capitals (Maurya_Capital, Greece_Capital, etc.) are CITY assets, not
    improvements — they don't appear in `improvement.xml` because the game
    spawns them via `Tile.cs:13029` (`infos.nation(eNation).meUrbanAsset`),
    not via the improvement renderer.

    To discover them via XML, we scan AssetVariation entries whose zType
    matches `ASSET_VARIATION_CITY_*_CAPITAL` and resolve them through the
    same SingleAsset → zAsset chain.

    Returns the same `ImprovementAsset` shape as `load_improvement_assets`
    (z_type and asset_z_type both refer to the variation/asset zType, since
    there's no `<zIconName>` field on these). Output filename will be
    `IMPROVEMENT_3D_<NATION>_CAPITAL.png` (e.g. `..._MAURYA_CAPITAL.png`)
    matching the historical naming.
    """
    if not xml_dir.exists():
        return []

    variations = _build_variation_index(_load_entries(xml_dir, ASSET_VARIATION_FILES))
    assets = _build_asset_index(_load_entries(xml_dir, ASSET_FILES))

    out: list[ImprovementAsset] = []
    for z_type, variation in variations.items():
        if not z_type.startswith("ASSET_VARIATION_CITY_") or not z_type.endswith("_CAPITAL"):
            continue
        best_asset_z, best_weight = max(variation.candidates, key=lambda c: c[1])
        prefab = assets.get(best_asset_z)
        if not prefab:
            logger.debug("%s → %s: asset not found", z_type, best_asset_z)
            continue
        # Canonical name: strip the ASSET_VARIATION_CITY_ prefix.
        # ASSET_VARIATION_CITY_MAURYA_CAPITAL → MAURYA_CAPITAL.
        canonical = z_type.removeprefix("ASSET_VARIATION_CITY_")
        out.append(
            ImprovementAsset(
                z_icon_name=canonical,
                prefab_name=prefab,
                z_type=z_type,
                asset_z_type=best_asset_z,
                weight=best_weight,
            )
        )
    return out


@dataclass(frozen=True)
class UrbanRenderableImprovement:
    """One urban-buildable improvement, paired with its nation lock if any.

    `nation_prereq` is `None` for universal improvements (Library, Forum,
    Bath, Theater, etc. — buildable in any nation's city). When set, the
    improvement only renders on that one nation's urban tile (shrines
    pinned via `<NationPrereq>`, dynasty-pinned wonders via the
    `_DYNASTY_TO_NATION` fallback).
    """

    z_icon_name: str  # canonical name; used in output filename
    z_type: str  # the actual XML entry (for diagnostics)
    prefab_name: str  # last segment of zAsset path; pass to find_root_gameobject
    nation_prereq: str | None


def _load_urban_compatible_terrain_targets(xml_dir: Path) -> frozenset[str]:
    """Resolve `terrainTarget.xml` to the set of `TERRAIN_TARGET_*` values
    whose `<Terrains>` list includes `TERRAIN_URBAN`.

    Improvements declare valid terrain via `<TerrainValid><zValue>TARGET</zValue>
    ...</TerrainValid>` where each TARGET resolves through `terrainTarget.xml`
    to a list of concrete `TERRAIN_*` values. An improvement renders inside
    the urban-tile composite if ANY of its targets includes `TERRAIN_URBAN`
    (or it has no `<TerrainValid>` at all — e.g. Hanging Gardens, accepted
    everywhere except `<TerrainInvalid>`).

    Examples (from the actual XML):
      - TERRAIN_TARGET_DRY     → {ARID, SAND}                — no urban
      - TERRAIN_TARGET_HILL    → height-based                 — no urban
      - TERRAIN_TARGET_HABITABLE → {URBAN, ARID, TEMPERATE, LUSH} — yes
      - TERRAIN_TARGET_URBAN   → {URBAN}                       — yes
    """
    out: set[str] = set()
    for entry in _load_entries(xml_dir, TERRAIN_TARGET_FILES):
        z_type = _entry_text(entry, "zType")
        if not z_type:
            continue
        terrains = entry.find("Terrains")
        if terrains is None:
            continue
        for child in terrains.findall("zValue"):
            if child.text and child.text.strip() == TERRAIN_URBAN:
                out.add(z_type)
                break
    return frozenset(out)


def _is_urban_renderable(
    entry: ET.Element,
    urban_compatible_targets: frozenset[str],
) -> bool:
    """Decide if an improvement entry should produce urban-tile composite
    renders. Filter rules (verified via the wonder + shrine investigation):

    - Must have `<bUrban>1</bUrban>` (the canonical urban-eligibility flag).
    - If `<TerrainValid>` is present, at least one of its `<zValue>` targets
      must resolve to a terrain list containing `TERRAIN_URBAN` — otherwise
      the improvement is locked to non-urban terrain (Pyramids on DRY,
      Acropolis on HILL, etc.). No `<TerrainValid>` at all means accepted
      anywhere, including urban (Hanging Gardens behavior).
    - Must NOT be gated by `<GameContentRequired>EVENTPACK_*</...>`
      (scenario-only event content; per the user, we don't ship those).

    Other DLC gates (`EMPIRES_OF_THE_INDUS`, `WONDERS_DYNASTIES`, etc.)
    pass through — those are real-game additions, not scenarios.
    """
    if _entry_text(entry, "bUrban") != "1":
        return False
    tv = entry.find("TerrainValid")
    if tv is not None:
        targets = [c.text.strip() for c in tv.findall("zValue") if c.text and c.text.strip()]
        if targets and not any(t in urban_compatible_targets for t in targets):
            return False
    gate = _entry_text(entry, "GameContentRequired")
    return gate is None or not gate.startswith("EVENTPACK_")


def _resolve_nation_lock(entry: ET.Element) -> str | None:
    """Extract the nation lock for an urban-renderable improvement.

    Priority: explicit `<NationPrereq>` first; then `<DynastyPrereq>` mapped
    via `_DYNASTY_TO_NATION`. Returns `None` for universal improvements
    (no lock — render on every urban tile).
    """
    nation = _entry_text(entry, "NationPrereq")
    if nation:
        return nation
    dynasty = _entry_text(entry, "DynastyPrereq")
    if dynasty:
        mapped = _DYNASTY_TO_NATION.get(dynasty)
        if mapped is not None:
            return mapped
        logger.debug(
            "Improvement with DynastyPrereq=%s has no _DYNASTY_TO_NATION mapping; "
            "treating as universal",
            dynasty,
        )
    return None


def load_urban_renderable_improvements(xml_dir: Path) -> list[UrbanRenderableImprovement]:
    """Discover every improvement that should render inside an urban-tile
    composite, paired with its nation lock if any.

    Walks `URBAN_IMPROVEMENT_FILES`, applies `_is_urban_renderable`, captures
    `<NationPrereq>`/`<DynastyPrereq>`, and resolves the prefab name through
    the same `assetVariation.xml → asset.xml` chain used by
    `load_improvement_assets`. Dedupes on `z_icon_name` (first wins —
    matches the existing tier-collapsing behavior, so Library_1 is rendered
    in place of Library_2/3 on the urban composite).

    Returns an empty list if `xml_dir` doesn't exist.
    """
    if not xml_dir.exists():
        logger.warning("XML directory not found: %s", xml_dir)
        return []

    improvement_xml = _load_entries(xml_dir, URBAN_IMPROVEMENT_FILES)
    variations = _build_variation_index(_load_entries(xml_dir, ASSET_VARIATION_FILES))
    assets = _build_asset_index(_load_entries(xml_dir, ASSET_FILES))
    urban_compatible_targets = _load_urban_compatible_terrain_targets(xml_dir)

    # Dedupe key is (z_icon_name, nation_prereq):
    #   - Universal improvements (nation_prereq=None): collapses upgrade
    #     tiers (Library_1/2/3 share zIconName=IMPROVEMENT_LIBRARY → one
    #     entry, basic-tier first wins).
    #   - Nation-locked shrines: 11 shared art assets across nations means
    #     several shrines share a zIconName (Greek Zeus + Babylonian
    #     Marduk both use IMPROVEMENT_SHRINE_KINGSHIP), but they're
    #     distinct PNGs because they appear on different urban tiles.
    #     Including nation_prereq in the key keeps them separate.
    seen: set[tuple[str, str | None]] = set()
    out: list[UrbanRenderableImprovement] = []
    skipped_filter = 0
    skipped_no_chain = 0
    skipped_dup = 0

    for entry in improvement_xml:
        z_type = _entry_text(entry, "zType")
        if not z_type:
            continue
        if not _is_urban_renderable(entry, urban_compatible_targets):
            skipped_filter += 1
            continue
        z_icon_name = _entry_text(entry, "zIconName") or z_type
        nation_prereq = _resolve_nation_lock(entry)
        key = (z_icon_name, nation_prereq)
        if key in seen:
            skipped_dup += 1
            continue
        asset_var = _entry_text(entry, "AssetVariation")
        if not asset_var:
            skipped_no_chain += 1
            continue
        variation = variations.get(asset_var)
        if variation is None:
            skipped_no_chain += 1
            continue
        best_asset_z, _w = max(variation.candidates, key=lambda c: c[1])
        prefab = assets.get(best_asset_z)
        if not prefab:
            skipped_no_chain += 1
            continue
        seen.add(key)
        out.append(
            UrbanRenderableImprovement(
                z_icon_name=z_icon_name,
                z_type=z_type,
                prefab_name=prefab,
                nation_prereq=nation_prereq,
            )
        )

    if skipped_filter or skipped_no_chain or skipped_dup:
        logger.info(
            "load_urban_renderable_improvements: %d resolved, "
            "%d filtered (non-urban / scenario / terrain-locked), "
            "%d no chain, %d duplicate icon",
            len(out),
            skipped_filter,
            skipped_no_chain,
            skipped_dup,
        )

    return out


def load_improvement_assets(xml_dir: Path) -> list[ImprovementAsset]:
    """
    Walk the improvement → variation → asset chain across base + DLC XML.

    For each improvement reachable through the full chain, return one
    `ImprovementAsset`. SingleAsset variations contribute one entry.
    `aiRandomAssets` variations contribute one entry: the highest-weighted
    candidate (ties broken by document order). The full weight is preserved
    on the returned object so callers can later switch to "render all".

    Improvements with broken chains (no AssetVariation, no Asset, missing
    prefab path) are skipped silently with a debug-level log. Returns an
    empty list if the XML directory has no recognizable files.
    """
    if not xml_dir.exists():
        logger.warning("XML directory not found: %s", xml_dir)
        return []

    improvement_entries = _build_improvement_entries(_load_entries(xml_dir, IMPROVEMENT_FILES))
    variations = _build_variation_index(_load_entries(xml_dir, ASSET_VARIATION_FILES))
    assets = _build_asset_index(_load_entries(xml_dir, ASSET_FILES))

    # Dedupe on z_icon_name; first improvement entry seen for a given icon
    # wins. Document order in improvement.xml roughly tracks tier order
    # (Library_1 before Library_2), so this picks the lowest tier.
    seen_icons: set[str] = set()
    out: list[ImprovementAsset] = []
    skipped_no_variation = 0
    skipped_no_asset = 0
    skipped_duplicate_icon = 0

    for entry in improvement_entries:
        if entry.z_icon_name in seen_icons:
            skipped_duplicate_icon += 1
            continue
        variation = variations.get(entry.asset_variation)
        if variation is None:
            logger.debug("%s → %s: variation not found", entry.z_type, entry.asset_variation)
            skipped_no_variation += 1
            continue
        # Pick the highest-weighted candidate; ties broken by first-seen order.
        best_asset_z, best_weight = max(variation.candidates, key=lambda c: c[1])
        prefab = assets.get(best_asset_z)
        if not prefab:
            logger.debug(
                "%s → %s → %s: asset not found",
                entry.z_type,
                entry.asset_variation,
                best_asset_z,
            )
            skipped_no_asset += 1
            continue
        seen_icons.add(entry.z_icon_name)
        out.append(
            ImprovementAsset(
                z_icon_name=entry.z_icon_name,
                prefab_name=prefab,
                z_type=entry.z_type,
                asset_z_type=best_asset_z,
                weight=best_weight,
            )
        )

    if skipped_no_variation or skipped_no_asset or skipped_duplicate_icon:
        logger.info(
            "load_improvement_assets: %d resolved, %d no-variation, %d no-asset, %d duplicate-icon",
            len(out),
            skipped_no_variation,
            skipped_no_asset,
            skipped_duplicate_icon,
        )

    return out
