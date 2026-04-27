# Improvement Names Aligned with Game's `zIconName` — IMPLEMENTED

> **Status**: shipped. Both `IMPROVEMENT_MESHES` (~66 entries) and `COMPOSITE_PREFABS` (~12 entries) are gone; the extractor now discovers improvements from `Reference/XML/Infos/` at runtime via `src/pinacotheca/asset_index.py`.

## Why we did this

The previous hand-curated `IMPROVEMENT_MESHES` list in `extractor.py` had drifted from what the game calls these improvements, both in **naming** (`MINISTRY` vs canonical `MINISTRIES`, `KUSHITE_PYRAMID` vs `KUSH_PYRAMID`, etc.) and in **asset selection** (the most striking example: our `("Courthouse_low", "COURTHOUSE")` rendered an *unused* `Courthouse_low` mesh — the game actually uses the `Palace` prefab for `IMPROVEMENT_COURTHOUSE`).

The latter forced misleading workarounds: the COURTHOUSE asset rendered backwards, leading us to add a per-asset rotation override that was actually papering over the wrong-prefab bug.

We now treat the game's XML chain as the single source of truth.

## Source of truth

The game ships a complete improvement → asset chain in `Reference/XML/Infos/`:

```
improvement.xml
  <Entry>
    <zType>IMPROVEMENT_BATHS_1</zType>             ← gameplay enum
    <zIconName>IMPROVEMENT_COLD_BATHS</zIconName>  ← what consumers look up
    <AssetVariation>ASSET_VARIATION_IMPROVEMENT_BATHS_1</AssetVariation>
  </Entry>
        ↓
assetVariation.xml
  <Entry>
    <zType>ASSET_VARIATION_IMPROVEMENT_BATHS_1</zType>
    <SingleAsset>ASSET_IMPROVEMENT_BATHS_1</SingleAsset>
  </Entry>
        ↓
asset.xml
  <Entry>
    <zType>ASSET_IMPROVEMENT_BATHS_1</zType>
    <zAsset>Prefabs/Improvements/Baths_Cold</zAsset>  ← Unity prefab path
  </Entry>
```

Three lookups give us everything: the canonical icon name (PNG output), the Unity GameObject (prefab to walk), and the gameplay tier metadata. No hand-curation needed.

The chain handles **visual tiers** correctly: `IMPROVEMENT_LIBRARY_1`, `_2`, `_3` are gameplay tiers but visually distinct improvements (Library → Academy → University), each with its own `zIconName` and prefab. Today we're already extracting all three by hand; with XML-driven extraction we get them automatically.

## Current drift

About half of our existing `IMPROVEMENT_3D_*.png` filenames don't match the game's `zIconName`:

| Our PNG | Game's `zIconName` (suffix only) | Drift type |
|---|---|---|
| `MINISTRY` | `MINISTRIES` | singular vs plural |
| `CHRISTIAN_TEMPLE` / `_CATHEDRAL` / `_MONASTERY` | `CHRISTIANITY_TEMPLE` / ... | religion adjective vs noun |
| `JEWISH_*` (2) | `JUDAISM_*` | religion adjective vs noun |
| `MANICHEAN_*` (3) | `MANICHAEISM_*` | religion adjective vs noun |
| `ZOROASTRIAN_*` (2) | `ZOROASTRIANISM_*` | religion adjective vs noun |
| `FIRE_SHRINE` (and 10 other shrines) | `SHRINE_FIRE` (etc.) | word order |
| `KUSHITE_PYRAMID` | `KUSH_PYRAMID` | adjective form |
| `HANGING_GARDEN` | `HANGING_GARDENS` | singular vs plural |
| `PYRAMID_LVL_1`–`4` | `PYRAMIDS` (the wonder; lvl_X are construction stages) | wrong asset |
| `GARRISON` | `GARRISON_1` / `_2` / `_3` | tier collapse |
| `BATHS_COLD` / `WARM` / `HEATED` (just-shipped) | `COLD_BATHS` / `WARM_BATHS` / `HEATED_BATHS` | word order — **fixed in companion PR** |

**Already-aligned names** (no change needed): ACADEMY, AMPHITHEATER, BARRACKS, COURTHOUSE, FAIR, GRANARY, GROCER, HAMLET, ISHTAR_GATE, LIBRARY, LUMBERMILL, MARKET, MINE, ODEON, PALACE, PASTURE, QUARRY, RANGE, ROYAL_LIBRARY, THEATER, UNIVERSITY, VILLAGE, WATERMILL, plus the renamed baths.

## What was implemented

`src/pinacotheca/asset_index.py` parses the chain at extraction time:

1. **improvement.xml** + `improvement-event.xml` → `(zType, zIconName, AssetVariation)` tuples.
2. **assetVariation.xml** + DLC variants (`-btt`, `-eoti`, `-wd`) → `AssetVariation → SingleAsset` (or weighted `aiRandomAssets` list).
3. **asset.xml** + DLC variants → `SingleAsset → zAsset` path.
4. Leaf component of `zAsset` is the Unity GameObject name passed to `prefab.find_root_gameobject`.
5. Output PNG: `IMPROVEMENT_3D_{zIconName.removeprefix("IMPROVEMENT_")}.png`.

Public API: `load_improvement_assets(xml_dir: Path) -> list[ImprovementAsset]`. Returns one entry per unique `zIconName` after deduplication. The extractor also calls a small `SUPPLEMENTAL_PREFABS` list for prefabs not in `improvement.xml` (only the four pyramid construction stages today).

### Decisions made during implementation

- **Dedupe by `zIconName`, first-seen wins.** Multiple `<zType>` entries often share a `<zIconName>` — most often upgrade tiers where the basic-tier and upgraded-tier visualize the same way (e.g., `IMPROVEMENT_LIBRARY_1`/`_2`/`_3` happen to map to *different* zIconNames `LIBRARY`/`ACADEMY`/`UNIVERSITY`, but the COURTHOUSE chain has all three tiers using `IMPROVEMENT_COURTHOUSE`-prefixed names). Document order in improvement.xml roughly tracks tier order, so first-seen picks the lowest tier.
- **`aiRandomAssets`: render the highest-weighted variant only.** The 30 `aiRandomAssets` entries in base XML are all terrain-tile variations (no improvement uses them today), but we support them anyway. Rendering all variants would multiply PNG count for marginal value; the `weight` field is preserved on `ImprovementAsset` so callers can switch to render-all later.
- **Skip improvements with broken chains** (no AssetVariation, missing asset, etc.) — log + count, don't fail.
- **Don't dedupe by prefab.** If `IMPROVEMENT_COURTHOUSE` and `IMPROVEMENT_PALACE` both resolve to `Prefabs/Improvements/Palace`, we render that prefab twice — once per improvement — so each gets its own canonical PNG. (This actually doesn't happen in current data: per the chain, `IMPROVEMENT_COURTHOUSE` → `Palace` and `IMPROVEMENT_PALACE` → `Ministry`. But the principle holds.)
- **No dedicated DLC-presence check.** All four DLC asset/variation files are loaded if present; missing ones are silently skipped (debug-logged). A user with a fresh non-DLC install will still get base-game extraction.

### Outcome

Single-pass extraction (no separate composite path; `find_root_gameobject` + `walk_prefab` handle both). 116 improvements discovered via XML + 4 supplemental = ~120 jobs. Typical run yields ~96 rendered + ~20 skipped (mostly missing diffuse textures on abstract markers like CITY_SITE, OUTPOST_RUINS).

The COURTHOUSE rotation override has been removed — the wrong-prefab bug is gone, so the override is unneeded.

## Known issue: PREFAB_DECODE_BLACKLIST

A small constant in `extractor.py`. Some prefabs (currently just `Fort`) trigger a **SIGSEGV** in UnityPy's C-level texture decoder when reading specific Texture2D assets (`Material.001_Diff` for Fort). Python `try/except` cannot catch SIGSEGV, so we maintain a hard-coded skip list. A subprocess-per-asset isolation strategy would be more principled but is deferred until the blacklist grows past a handful of entries.

## Migration

This is a breaking change for callers hard-coding old PNG filenames. Per the per-ankh feature request, downstream consumers want the canonical zIconName naming — the rename fixes their lookup. Web gallery regenerates from filesystem so it picks up new names automatically.

## Critical files

- `src/pinacotheca/asset_index.py` — XML chain parser; pure-Python, no UnityPy dep.
- `src/pinacotheca/extractor.py` — `extract_improvement_meshes` calls `load_improvement_assets()` and iterates results + `SUPPLEMENTAL_PREFABS`. `extract_composite_meshes` and the raw-mesh fallback are gone.
- `tests/test_asset_index.py` — synthetic-XML tests for the chain semantics.
- `docs/extracting-3d-buildings.md` — updated to describe the XML chain instead of the curated lists.

## Related work (still relevant follow-ups)

- **Per-family asset variants** (per-ankh's Ask 2): different culture/family meshes for the same improvement type. The XML chain doesn't currently distinguish these — needs further investigation, possibly a separate XML table.
- **Subprocess-per-asset isolation** to robustly handle SIGSEGV-causing prefabs without a hard-coded blacklist.
- **Splat-Y plinth + 180° rotation work** (already shipped) — orthogonal; this XML-discovery work composes with it cleanly.
