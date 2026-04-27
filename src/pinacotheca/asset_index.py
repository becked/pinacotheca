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
