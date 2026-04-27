# Feature: Align Improvement Names with Game's `zIconName`

## Why this matters

Pinacotheca currently maintains a hand-curated `IMPROVEMENT_MESHES` list in `src/pinacotheca/extractor.py` mapping Unity GameObject names to PNG output names. The output names were chosen ad-hoc when the list was first written and have **drifted** from what the game itself calls these improvements.

Downstream consumers (per-ankh, future map renderers, anything pulling from game data) query the game's data tables and get back canonical names — `IMPROVEMENT_COLD_BATHS`, `IMPROVEMENT_SHRINE_FIRE`, `IMPROVEMENT_CHRISTIANITY_TEMPLE`. They want to look up our PNGs by that key and find them. Today, the lookup misses.

We should treat the game's XML as the **single source of truth** and stop maintaining a parallel naming convention.

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

## Proposed implementation

Replace the hand-maintained `IMPROVEMENT_MESHES` list with XML-driven discovery:

1. **Parse `Reference/XML/Infos/improvement.xml`** at extraction time. For each `<Entry>`, capture `zIconName` and `AssetVariation`.
2. **Parse `assetVariation.xml`** to resolve `AssetVariation` → `SingleAsset`.
3. **Parse `asset.xml`** to resolve `SingleAsset` → `zAsset` (e.g., `Prefabs/Improvements/Baths_Cold`).
4. **Take the leaf name** of `zAsset` as the GameObject to walk (`Baths_Cold`).
5. **Output PNG** as `IMPROVEMENT_3D_<NAME>.png` where `<NAME>` is the `zIconName` minus the `IMPROVEMENT_` prefix.
6. Same chain works for **DLC**: parse `improvement-eoti.xml`, `improvement-sap.xml`, `assetVariation-eoti.xml`, etc. (probably 2–3 file pairs to merge).
7. **Wonders** (currently `COMPOSITE_PREFABS`): same machinery applies — they're also `improvement.xml` entries with `zIconName` like `IMPROVEMENT_PYRAMIDS`, `IMPROVEMENT_HANGING_GARDENS`. The composite-vs-single distinction can be detected at walk-time (does the prefab have multiple meaningful MeshFilter leaves?), not maintained by hand.

This drops both `IMPROVEMENT_MESHES` and `COMPOSITE_PREFABS` entirely. New game improvements get extracted automatically without code changes.

## Migration considerations

This is a breaking change for anyone consuming our PNG filenames.

- **Per-ankh**: confirmed they want zIconName-keyed lookups, so a clean rename is positively welcome — but they'll need to know the renames so their bake/lookup updates land at the same time.
- **Web gallery** (`web/scripts/generate-manifest.ts`): regenerates from filesystem, so it'll just pick up the new names. No code change needed.
- **Versioning**: ship as a major version bump (v2.0). Document the full rename mapping in `CHANGELOG.md`.
- **Optional transition**: write both old and new names for one release cycle (symlinks or duplicate writes) to give consumers time to migrate. Probably not worth it — coordinate the rename with downstream and cut clean.

## Open investigations before implementing

- **Which XML files exist across DLC?** Need to enumerate all `improvement-*.xml`, `assetVariation-*.xml`, `asset-*.xml` files so the parser merges them all.
- **Gaps in the asset chain**: not every `<Entry>` in `improvement.xml` has all three links populated. Need to handle missing `AssetVariation` (some improvements may be data-only or icon-only) and missing prefabs gracefully — log and skip, don't crash.
- **Multi-asset prefabs**: assetVariation.xml has `<SingleAsset>` for most entries but probably also a `<MultiAsset>` form for things with random/seasonal variants. Check whether any improvements use this; if so, decide whether to render one variant or many.
- **Same-asset duplication**: multiple `zType` entries can resolve to the same `zAsset` (e.g., the placeholder Indian urban tile reuses Assyria's PVT). Don't render the same prefab twice; dedupe by zAsset path.
- **Naming for wonder construction stages**: `Pyramid_lvl_1`–`4` aren't in `improvement.xml` as separate entries — they're the construction visualization for `IMPROVEMENT_PYRAMIDS`. Probably out of scope for the curated extraction; a separate "construction stages" output category if desired.

## Related work

- Bath / MINISTRY rename done in companion PR (small, immediate fixes for the most visible drifts the user explicitly called out)
- Pyramid asset-list correction (`Pyramid_lvl_X` → `Pyramids`) — would happen automatically once XML-driven extraction lands
- Per-family asset variants (per-ankh's Ask 2 in `feature-request-per-ankh-map-atlas.md`) — also depends on understanding the AssetVariation table; may overlap with this work
- Splat-filter + plinth-strip work (already shipped) — orthogonal, no interaction
