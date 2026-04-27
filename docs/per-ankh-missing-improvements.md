# Missing 3D Improvement Assets (Per-Ankh Map)

Source request: per-ankh's hex map renderer (`scripts/bake-improvements-test.ts`) currently consumes pinacotheca's `IMPROVEMENT_3D_*.png` outputs. The original 2026-04-27 snapshot had 67 assets; the XML-driven discovery work (commit `86a99ce`) lifted that to ~112. The full list at the bottom of this doc reflects the original 67 — many of the entries below have since been picked up automatically by canonical-name discovery; audit before treating as authoritative gaps.

Per-ankh's bake script auto-picks up new assets — drop a new PNG into `extracted/sprites/improvements/` and per-ankh's existence-check + tier-down fallback resolves it on the next bake. No coordination needed for individual asset additions.

## Tier-family completions (10)

These complete tier families per-ankh has partially mapped:

| Family | Missing assets |
|---|---|
| Settlement | `TOWN`, `CITY` (XML zType: `SETTLEMENT_3`, `SETTLEMENT_4`) |
| Ruins | `HOVEL_RUINS`, `OUTPOST_RUINS`, `ENCAMPMENT_RUINS`, `BASTION_RUINS` (entire family — XML zType: `RUINS_1` through `_4`) |
| Aksum Stele | `AKSUM_STELE_1`, `AKSUM_STELE_2`, `AKSUM_STELE_3` (entire family) |

Note: per-ankh expects the in-game-display-name pattern that's already established for Garrison (`GARRISON / STRONGHOLD / CITADEL`) and Settlement tiers 1–2 (`HAMLET / VILLAGE`). Tiers 3–4 of Settlement should follow as `TOWN / CITY`.

## Religious matrix gaps (12)

Naming pattern for existing assets: `<RELIGION>_<BUILDING>` (e.g. `CHRISTIAN_TEMPLE`).

| Religion | Temple | Monastery | Cathedral | Holy Site |
|---|---|---|---|---|
| Buddhist | ✗ | ✗ | ✗ | ✗ |
| Christian | ✓ | ✓ | ✓ | ✗ |
| Hindu | ✗ | ✗ | ✗ | (no DB usage — skip) |
| Jewish | ✓ | ✓ | ✗ | ✗ |
| Manichean | ✓ | ✓ | ✓ | ✗ |
| Zoroastrian | ✗ | ✓ | ✓ | ✗ |

Specific missing:

- `BUDDHIST_TEMPLE`, `BUDDHIST_MONASTERY`, `BUDDHIST_CATHEDRAL`, `BUDDHIST_HOLY_SITE`
- `HINDU_TEMPLE`, `HINDU_MONASTERY`, `HINDU_CATHEDRAL`
- `JEWISH_CATHEDRAL`, `JEWISH_HOLY_SITE`
- `ZOROASTRIAN_TEMPLE`, `ZOROASTRIAN_HOLY_SITE`
- `CHRISTIAN_HOLY_SITE`, `MANICHEAN_HOLY_SITE`

`ZOROASTRIAN_TEMPLE` is conspicuous — the cathedral and monastery exist, only the temple is absent. Likely an oversight.

## Common rural/urban (high DB volume) (8)

These represent a lot of tile coverage in real saves; their absence leaves large areas of the map unstyled:

| Asset | DB type | Approx. instances in test saves |
|---|---|---|
| `FARM` | `IMPROVEMENT_FARM` | 4,189 |
| `NETS` | `IMPROVEMENT_NETS` | 1,622 |
| `WINDMILL` | `IMPROVEMENT_WINDMILL` | 1,300 |
| `GROVE` | `IMPROVEMENT_GROVE` | 1,100 |
| `CAMP` | `IMPROVEMENT_CAMP` | 1,047 |
| `HARBOR` | `IMPROVEMENT_HARBOR` | 690 |
| `FORT` | `IMPROVEMENT_FORT` | (low volume, common in early game) |
| `CITY_SITE`, `SLUMS` | various | low |

## Wonders / unique buildings (33)

- `ACROPOLIS`
- `AL_KHAZNEH`
- `ALTAR_ATEN`
- `ANCIENT_RUINS`
- `APADANA`
- `BALEARIC_RANGE`
- `BURIAL_CHAMBER`
- `CIRCUS_MAXIMUS`
- `COLOSSEUM`
- `COLOSSUS`
- `COTHON`
- `ESTATES`
- `GREAT_ZIGGURAT`
- `HAGIA_SOPHIA`
- `HELIOPOLIS`
- `HILL_FORT`
- `JEBEL_BARKAL`
- `JERWAN_AQUEDUCT`
- `LAURION_MINE`
- `LIGHTHOUSE`
- `MAUSOLEUM`
- `MINOR_CITY`
- `MONUMENTAL_BUDDHAS`
- `MUSAEUM`
- `NECROPOLIS`
- `ORACLE`
- `PANTHEON`
- `PILLAR_EDICT`
- `PYRAMIDS` *(distinct from existing `PYRAMID_LVL_1`–`4` construction stages — this is the completed wonder)*
- `STUPA`
- `THE_MAHAVIHARA`
- `VIA_RECTA_SOUK`
- `YAZILIKAYA`

## Naming questions to clarify

### 1. Shrines — god → theme mapping

The DB has 50+ shrine types keyed by god name (`IMPROVEMENT_SHRINE_AMUN`, `_ANAHITA`, `_ATHENA`, `_ASHUR`, `_ZEUS`, etc.). Pinacotheca currently extracts 11 generic shrine assets keyed by *theme*:

`FIRE_SHRINE`, `HEALING_SHRINE`, `HEARTH_SHRINE`, `HUNTING_SHRINE`, `KINGSHIP_SHRINE`, `LOVE_SHRINE`, `SUN_SHRINE`, `UNDERWORLD_SHRINE`, `WAR_SHRINE`, `WATER_SHRINE`, `WISDOM_SHRINE`

**Question:** does each god have its own mesh, or do gods share meshes by classification (e.g. all war gods → `WAR_SHRINE`)? If the latter (likely), per-ankh needs the god → theme mapping (probably encoded somewhere in the game's XML or C# source). Without that mapping, per-ankh can't render shrines on the map at all.

### 2. Cults

The DB has these cult improvements:

- `AMAZON_CULT`, `CAVALRY_CULT`, `DUAL_CULT`, `ECSTATIC_CULT`, `SWORD_CULT`
- `CULT_OF_ISIS_AND_SERAPIS`, `CULT_OF_MITHRAS`, `CULT_OF_THE_ANGELIC_DIVINE`, `CULT_OF_THE_HEALER`, `CULT_OF_THE_MOTHER`
- `GODS_CONSORT_SHRINE`, `SHRINE_OF_THE_FALLEN_GODDESS`, `SHRINE_OF_THE_HERO`
- `SHRINE_TRIBE_PAGANISM`

No obvious 3D assets currently extracted for any of these. Confirm whether the meshes exist under different names (some might map to the existing 11 shrine themes via the same god → theme mapping above) or aren't extracted yet.

## Reference: full list of currently-shipped 3D assets (67)

For reference / dedup checking, here's what per-ankh sees today in `extracted/sprites/improvements/IMPROVEMENT_3D_*.png`:

```
ACADEMY, AKSUM_CAPITAL, AMPHITHEATER, BARRACKS, BRICKWORKS,
CHRISTIAN_CATHEDRAL, CHRISTIAN_MONASTERY, CHRISTIAN_TEMPLE, CITADEL,
COLD_BATHS, COURTHOUSE, ENCAMPMENT, FAIR, FIRE_SHRINE, GARRISON, GRANARY,
GROCER, HAMLET, HANGING_GARDEN, HEALING_SHRINE, HEARTH_SHRINE, HEATED_BATHS,
HUNTING_SHRINE, ISHTAR_GATE, JEWISH_MONASTERY, JEWISH_TEMPLE, KINGSHIP_SHRINE,
KUSHITE_PYRAMID, LIBRARY, LOVE_SHRINE, LUMBERMILL, MANICHEAN_CATHEDRAL,
MANICHEAN_MONASTERY, MANICHEAN_TEMPLE, MARKET, MAURYA_CAPITAL, MINE,
MINISTRIES, OBELISK, ODEON, OUTPOST, PALACE, PASTURE, PYRAMID_LVL_1,
PYRAMID_LVL_2, PYRAMID_LVL_3, PYRAMID_LVL_4, QUARRY, RANGE, ROYAL_LIBRARY,
STRONGHOLD, SUN_SHRINE, TAMIL_CAPITAL, THEATER, TOWER, UNDERWORLD_SHRINE,
UNIVERSITY, VILLAGE, WALL, WAR_SHRINE, WARM_BATHS, WATER_SHRINE, WATERMILL,
WISDOM_SHRINE, YUEZHI_CAPITAL, ZOROASTRIAN_CATHEDRAL, ZOROASTRIAN_MONASTERY
```
