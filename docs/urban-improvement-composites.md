# Urban-Improvement Composites

## Status: implemented

`extract_urban_composite_meshes` (in `src/pinacotheca/extractor.py`) renders a per-tile composite for every urban-buildable improvement nestled inside each compatible nation's urban tile, exactly the way the game composes the visible city scene at runtime. Output filenames: `IMPROVEMENT_3D_<NAME>_<NATION>_URBAN.png` in `extracted/sprites/improvements/`.

The existing single-improvement renders (`IMPROVEMENT_3D_<NAME>.png`, transparent background) are preserved untouched; the urban composites are new outputs alongside them. per-ankh consumers can look up `(tile.improvement, tile.urban_nation)` and fall back to `IMPROVEMENT_3D_<NAME>.png` when a composite doesn't exist for that pair.

## What it produces

For each urban-renderable improvement (filter rules below):
- **Universal** (no nation lock): one PNG per nation that has an urban tile (10 nations).
- **Nation-locked** (shrines via `<NationPrereq>`, dynasty-locked wonders via `<DynastyPrereq>`): one PNG, only on the matching nation's urban tile.

Three nations (Kush, Yuezhi, Tamil) have nation-locked improvements but no urban tile prefab — those improvements are skipped.

Approximate output cardinality: ~70 universal × 10 + ~50 nation-locked = ~750 PNGs.

## Filter rules (which improvements qualify)

`load_urban_renderable_improvements(xml_dir)` in `src/pinacotheca/asset_index.py` walks `improvement.xml` + `improvement-event.xml` + `improvement-event-sap.xml` and applies:

1. Must have `<bUrban>1</bUrban>` (the canonical urban-eligibility flag).
2. If `<TerrainValid>` is present, at least one of its `<zValue>` targets must resolve through `terrainTarget.xml` to a `<Terrains>` list containing `TERRAIN_URBAN`. Improvements like Pyramids (`TERRAIN_TARGET_DRY`) or Acropolis (`TERRAIN_TARGET_HILL`) have non-urban targets and are excluded — they always render as standalone tiles. Improvements with no `<TerrainValid>` at all (Hanging Gardens) are accepted (no terrain restriction).
3. Must NOT be gated by `<GameContentRequired>EVENTPACK_*</...>` (scenario-only event content). Other DLC gates pass through.

Nation lock comes from `<NationPrereq>` (52 nation-tied shrines + a handful of national wonders), or `<DynastyPrereq>` mapped through a small in-module table (currently only `DYNASTY_PTOLEMY → NATION_EGYPT` for the Serapis shrine).

Dedupe key is `(z_icon_name, nation_prereq)` — universal improvements collapse upgrade tiers (Library_1/2/3 → one entry), and nation-locked shrines that share a visual model across nations (Greek Zeus + Babylonian Marduk both use `IMPROVEMENT_SHRINE_KINGSHIP` as their icon) stay as distinct entries because their nation-lock keys differ.

## How the composite is built

Per `(improvement, nation)` pair:

1. **Walk the urban tile prefab once** (cached): `MeshFilter` parts (after `drop_splat_meshes`), the typed clutter expansion (each `(model, instance)` pair carries its resolved `TerrainClutterType` per `clutter_to_prefab_parts_with_type`), and the per-nation `TerrainTexturePVTSplat` planes.
2. **Walk the improvement prefab**: `MeshFilter` + clutter + any `TerrainClutterSplat` (`Clutter-Mask` / `ClutterSplat`-named child) planes.
3. **Cull the urban clutter** against the improvement's mask planes (`clutter_culling.cull_clutter_against_masks`). For each clutter instance: project its world XZ into each mask plane's local Plane-mesh UV, sample the channel matching its `TerrainClutterType` (R=Trees, G=MinorBuildings, B=MajorBuildings), combine across overlapping planes via `max`, then compare against `RandomStruct(0).next_float()`. If the mask value exceeds the random draw, the instance is hidden — exactly matching `ClutterTransformsBackgroundData.cs:158-162` runtime behavior.
4. **Render layered**: existing `render_layered_ground` orchestrates biome (TERRAIN_TEMPERATE) → urban PVT planes → urban-tile buildings layer (mesh + culled clutter) → improvement buildings layer (passed via `extra_building_parts`). The urban-tile and improvement parts go in **separate building layers**, not concatenated — see "Material domains" below.

The urban tile's own contribution (mesh + PVT + un-culled clutter) is byte-identical across improvements that don't mask anything from it, so the cache makes the per-improvement work cheap (just walk the improvement prefab once and run the cull).

## Material domains: why urban + improvement render as separate layers

`render_layered_ground` accepts `building_parts` and `extra_building_parts` as two distinct groups, each rendered as its own pass with its own texture lookup. This is required when the two groups come from different prefabs.

`prefab.find_diffuse_for_prefab` walks all materials in a parts list and picks the **single largest-area texture** to render the whole batch with. That works fine when all parts come from one prefab (the picker resolves to that prefab's diffuse). But when you concatenate parts from two different prefabs (e.g. Greek urban clutter + Pantheon mesh), the picker selects ONE texture across both, and that texture gets sampled with BOTH groups' UVs. The result is the wrong-prefab texture stretched across the other's geometry — visible as the Pantheon dome rendering with Greek house wall stripes, or vice versa.

We hit this concretely on Library/Pantheon/Theater/Royal Library composites during development; the fix was to render each material domain as its own building layer. The improvement and urban tile each get their own `find_diffuse_for_prefab` lookup, then PIL alpha-composites the layers in the right order. The same `bbox_override` shared across passes keeps them in spatial lockstep.

If a future caller needs to add a third material domain (e.g. an additional prefab type), extend the same pattern — `_bake_group` in `render_layered_ground` handles arbitrary parts groups via the same per-group texture resolution.

## RandomStruct port

`clutter_culling.RandomStruct` is a hand port of `decompiled/Mohawk.SystemCore/RandomStruct.cs` — a Park-Miller LCG (IA=16807, IQ=127773, IR=2836) with a `seed=0 → ulong.MaxValue` special case. All arithmetic uses Python ints masked to 64 bits to match C# ulong wrap-around in the subtraction term.

The seed used at runtime by `ClutterTransformsBackgroundData.cs:108` is hard-coded `RandomStruct(0)`. We re-use that, so consecutive runs of the extractor produce byte-identical outputs (deterministic culling is critical for diff-clean re-extractions).

## TerrainClutterSplat layout

Body is exactly 72 bytes after the 32-byte MonoBehaviour header. Field order matches the C# class declaration; each `[SerializeField]` bool is serialized as 1 byte then aligned to the next 4-byte boundary, so the three `clear*` flags contribute 12 bytes total. End-of-parse byte assertion in `parse_terrain_clutter_splat` fails loudly if a future patch reorders or adds fields.

Verified field values on the Library Clutter-Mask plane (and similar on Palace, Theater, Barracks): channel=2 (B channel), intensity=1.0, clear_trees=True + clear_minor=True (Library is medium-sized → clears small houses + trees but not major buildings), tiling=1.0.

## Mask plane mesh + UV projection

Every `TerrainClutterSplat` we've inspected uses Unity's built-in `Plane` mesh (`PathID=10209, FileID=3`, name `"Plane"`). Unity's Plane is a 10×10-unit grid in the local XZ plane, normal pointing +Y, with UV (0,0) at (-5, ?, -5) and UV (1,1) at (+5, ?, +5). It's NOT the smaller 1×1 Quad mesh.

This is load-bearing for the UV projection in `clutter_culling._world_to_local_plane_uv`. Earlier iterations assumed Quad (XY surface, [-0.5, 0.5] extent) — that produced near-zero culling because clutter instances at typical world positions projected outside the 1×1 footprint, and the local Y axis pointed UP rather than along the texture's V direction.

If a future prefab uses a different mesh (Quad, or a custom horizontal plane), the projection needs adjusting. Detect mesh type via `m_Name` on the MeshFilter mesh and dispatch accordingly.

## Why some composites look subtle

Smaller improvements (Theater, Barracks, Bath, single-tier shrines) have small Clutter-Mask plane footprints (~0.5–1.0 unit square). The Greek urban tile clutter spans ~8.5 × 8.3 units with 167 dense parts, so a small mask only culls 5–15 clutter pieces and the improvement appears as a small structure inside an otherwise-full city. This matches the in-game visual — those improvements are visually subtle inside dense cities.

Larger wonder-tier improvements (Royal Library, Hanging Gardens) have wider Clutter-Mask planes (1.3+ units) and significantly more clutter is culled, making them clearly visible. Visit `extracted/sprites/improvements/IMPROVEMENT_3D_ROYAL_LIBRARY_GREECE_URBAN.png` for an example.

## Edge clipping is a known limitation

Surrounding clutter pieces whose **pivot points** sit just outside the improvement's mask area survive culling, but their **mesh bodies** can extend INTO the improvement's footprint, producing visible clipping at building edges (a Greek house wall poking through the Academy's outer plaza, etc.).

This matches the game's own runtime culling rule. `ClutterTransformsBackgroundData.cs:158` decides each instance's visibility by sampling the cluttermap **only at the instance's world translation** (the GameObject's pivot), not at any other point on its mesh. We replicate that logic exactly. So an instance with pivot at world (X, 0, Z) where mask=0 stays visible regardless of how far its mesh extends past that pivot.

In-game the clipping is also present but less visible at typical map-view zoom (small per-tile pixel count smooths over edge artifacts). The full-resolution composite renders at 1500+ px and exposes the clipping clearly.

Investigated and confirmed there's NO additional culling mechanism we're missing:
- `ClutterMaskable` MonoBehaviour exists and is iterated by `ImprovementRenderer.MarkClutterDirty:269-288`, but **none of the prefabs we render** (Greek_Urban, Library, Pantheon, Academy, Theater, etc.) have `ClutterMaskable` components attached. Only `TerrainClutterSplat`, which we handle.
- The runtime cluttermap is built via the same orthographic projection of mask planes that we replicate offline.
- No baked per-tile clutter-removal data exists in the prefabs.

If a future prefab adds `ClutterMaskable` components, that path would need separate handling. For all current prefabs, the masking we do is complete.

A future maintainer wanting cleaner edges (deviating from game-faithful) could add a multi-sample option to `cull_clutter_against_masks` — sample at clutter centroid AND a small XZ offset, cull if any sample exceeds the random draw. Effectively grows the cull radius to cover clutter mesh extent. We deliberately did not implement this since the game itself doesn't.

## Files

- `src/pinacotheca/terrain_clutter_splat.py` — `TerrainClutterSplat` parser, walker, and per-channel mask compositor (3-channel image: R=Trees, G=Minor, B=Major).
- `src/pinacotheca/clutter_culling.py` — `RandomStruct` port + `cull_clutter_against_masks`.
- `src/pinacotheca/clutter_transforms.py` — `clutter_to_prefab_parts_with_type` returning per-instance `TerrainClutterType`.
- `src/pinacotheca/asset_index.py` — `load_urban_renderable_improvements` + filter helpers.
- `src/pinacotheca/extractor.py` — `extract_urban_composite_meshes` orchestrator.
- `src/pinacotheca/cli.py` — wires the new extractor into `pinacotheca`.
- Tests: `tests/test_terrain_clutter_splat.py`, `tests/test_clutter_culling.py`, `tests/test_clutter_transforms.py` (extension), `tests/test_asset_index.py` (extension).

## Re-rendering

```bash
# Force regenerate composites by deleting them; the extractor skips
# existing files. Existing IMPROVEMENT_3D_*.png (single-improvement
# renders) and IMPROVEMENT_3D_<NATION>_URBAN.png (empty urban tiles)
# are untouched and don't need deletion.
rm extracted/sprites/improvements/IMPROVEMENT_3D_*_*_URBAN.png

pinacotheca   # runs sprites + units + improvements + urban composites
```

## Gallery deployment

These composites are **excluded from the public gh-pages gallery** (and from
the SvelteKit manifest that drives it). They live in `extracted/sprites/` for
per-ankh's atlas pipeline but ship to ~1.3 GB across 719 files — pushing the
total deployed size over GitHub Pages' 1 GB hard cap. The deploy filter lives
in `src/pinacotheca/gallery_filter.py` and is documented in CLAUDE.md under
"Gallery deploy filter".

**Naming subtlety that matters here.** The exclusion glob is
`improvements/IMPROVEMENT_3D_*_*_URBAN.png` — the **two** `*` wildcards
between `IMPROVEMENT_3D_` and `_URBAN.png` are load-bearing. They match the
per-(improvement, nation) composites this doc is about (e.g.
`IMPROVEMENT_3D_LIBRARY_GREECE_URBAN.png`, two underscore-separated fields:
`LIBRARY` and `GREECE`). They do **not** match the standalone per-nation
urban-tile renders that this doc's predecessor work produced — those are
`IMPROVEMENT_3D_<NATION>_URBAN.png` with only one underscore-separated field
(e.g. `IMPROVEMENT_3D_GREECE_URBAN.png`). The 10 standalone urban tiles stay
in the gallery; the 719 composites do not. The same wildcard pattern is used
in the Re-rendering section above to delete only the composites, not the
underlying tiles — same load-bearing distinction.

If you ever wonder "why don't I see urban improvement composites in the local
dev gallery?" — the answer is that the manifest filter applies in dev as well
as prod (single source of truth, no env-flagged divergence), so the local
SvelteKit app reflects the deployed set. To inspect a filtered composite,
open the file directly from `extracted/sprites/improvements/`.
