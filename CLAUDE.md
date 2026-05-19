# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Pinacotheca is a Python tool for extracting and cataloging sprite assets from the game **Old World** (a 4X strategy game by Mohawk Games). It uses UnityPy to extract sprites directly from Unity asset bundles without requiring external tools like AssetRipper.

## Reference Materials (local-only symlinks)

Two symlinks at the repo root point to authoritative sources outside the project. Both are gitignored — they exist on the maintainer's machine and on Claude's. Read them freely; never copy their contents into the repo.

- **`reference/`** → game install's `Old World/Reference/` directory. Contains the shipped XML data (`XML/Infos`, `XML/Mods`, `XML/UI`), modding source (`Source/Base`, `Source/Mods`), and reference graphics. **Use this** as the source of truth for anything we parse out of the XML chain (improvement.xml, asset.xml, assetVariation.xml, resource.xml, DLC variants), for verifying field names, for sanity-checking enum values, and for finding new improvements/resources/units before they show up in extraction.

- **`decompiled/`** → decompiled C# of the game's assemblies (`Assembly-CSharp/`, `Mohawk.SystemCore/`, `TenCrowns.CarthageCampaign/`, `TenCrowns.GameCore/`). **Use this** as the source of truth for runtime behavior we have to mimic — camera setup, lighting, shader parameters, the `ClutterTransforms` MonoBehaviour layout, splat/PVT pipelines, mesh baking, anything where the XML data alone doesn't tell you how the game actually composes the visual. Most of the camera/rendering work in `renderer.py`, `layered_render.py`, and `clutter_transforms.py` was reverse-engineered from here.

When investigating anything visual or runtime-composed (new prefab type breaks, layout drift after a patch, "how does the game actually render X"), check `decompiled/` *before* guessing from extracted bytes. When investigating anything data-driven (new improvement/resource/unit, naming conventions, DLC additions), check `reference/XML/` and `reference/Source/`.

## Commands

```bash
# Setup virtual environment
python3 -m venv venv
source venv/bin/activate

# Install package with dev dependencies
pip install -e ".[dev]"

# Install web dependencies
cd web && npm install
```

### Core Workflow

```bash
# Extract sprites from Old World game assets
pinacotheca

# Run SvelteKit dev server
pinacotheca-web

# Build production gallery (outputs to extracted/)
pinacotheca-web-build

# Deploy gallery to GitHub Pages (gh-pages branch)
pinacotheca-deploy

# Generate texture atlases (local use, not deployed)
pinacotheca-atlas
```

### Other Commands

```bash
# Generate standalone HTML gallery (legacy, not part of main workflow)
pinacotheca-gallery

# Run tests
pytest

# Run linter and formatter
ruff check .
ruff format .

# Run type checker
mypy src/

# Bump version
python scripts/bump-version.py 1.2.0
```

## Architecture

### Package Structure

```
src/pinacotheca/
├── __init__.py              # Package exports
├── categories.py            # Sprite categorization (regex patterns, pre-compiled)
├── extractor.py             # UnityPy extraction (sprites, units, improvements, urban composites)
├── prefab.py                # GameObject/Transform walker, OBJ baker, splat/plinth filters
├── renderer.py              # moderngl 3D mesh rendering with building/unit cameras
├── atlas.py                 # Texture atlas generation
├── asset_index.py           # XML chain parser (improvement → assetVariation → asset)
├── biome_base.py            # TERRAIN_TEMPERATE biome base loader for layered renders
├── clutter_transforms.py    # ClutterTransforms MonoBehaviour decoder + expander
├── typetree.py              # TypeTreeGenerator setup; routes MonoBehaviour decode through UnityPy
├── clutter_culling.py       # RandomStruct + probabilistic clutter cull pass
├── layered_render.py        # Biome + PVT + buildings layered orchestrator
├── pvt_splats.py            # TerrainTexturePVTSplat parser + texture compositor
├── terrain_clutter_splat.py # TerrainClutterSplat parser + per-channel mask compositor
├── gallery.py               # HTML gallery generator (legacy)
├── cli.py                   # Command-line interface entry points
└── py.typed                 # PEP 561 marker for type hints

docs/                 # Investigation writeups, feature requests, references
├── extracting-3d-buildings.md
├── extracting-game-assets-from-unity-with-python.md
├── atlas-reference.md
├── improvement-naming-alignment.md       # Canonical zIconName follow-up effort
├── runtime-composed-cities.md            # ClutterTransforms parser for sparse capitals + urban tiles
└── urban-improvement-composites.md       # Per-(improvement, nation) urban-tile composites with mask culling

web/                  # SvelteKit gallery (primary web interface)
├── scripts/
│   └── generate-manifest.ts  # Build-time sprite scanner
├── src/
│   ├── lib/
│   │   ├── components/       # Svelte components (Sidebar, SpriteGrid, etc.)
│   │   ├── utils/            # Categories, search (Fuse.js), URL state
│   │   └── types.ts          # TypeScript interfaces
│   ├── routes/
│   │   └── +page.svelte      # Main gallery page
│   └── data/
│       └── manifest.json     # Generated sprite metadata
└── svelte.config.js          # Outputs to ../extracted/

reference/            # SYMLINK → game install Reference/ (XML, Source, Graphics) — gitignored
decompiled/           # SYMLINK → decompiled C# assemblies — gitignored, local-only
```

### Key Modules

- **`categories.py`**: Defines `CATEGORIES` dict mapping category names to regex patterns. Patterns are pre-compiled for performance. The `categorize()` function returns the category for a sprite name.

- **`extractor.py`**: Four extraction entry points called in sequence by `pinacotheca`:
  - `extract_sprites()` — 2D sprite extraction (the original 4000+ icon set)
  - `extract_unit_meshes()` — 3D unit mesh renders (`UNIT_3D_*.png`)
  - `extract_improvement_meshes()` — 3D improvement renders (`IMPROVEMENT_3D_*.png` for improvements/capitals/urbans, `RESOURCE_3D_*.png` for resources). Discovers the asset list at runtime from the game's XML chain via `asset_index.py`. Includes a small `SUPPLEMENTAL_PREFABS` list for things not in `improvement.xml` (currently only the four pyramid construction stages) and `PREFAB_DECODE_BLACKLIST` for prefabs whose Texture2D decode SIGSEGVs UnityPy. Resources are tile-level decorations (animals, crops, ore deposits) the game composites independently of the improvement on top — the Pasture *fence* lives in the improvement prefab; the herd of horses/sheep/cattle on the tile under it lives in `Prefabs/Resource/<animal>`.
  - `extract_urban_composite_meshes()` — per-(improvement, nation) urban-tile composites (`IMPROVEMENT_3D_<NAME>_<NATION>_URBAN.png`). Replicates the in-game runtime composition: improvement nestled inside the nation's urban tile with biome + PVT + clutter-culled background underneath. Filter via `load_urban_renderable_improvements()`; cull via `clutter_culling.cull_clutter_against_masks` matching the runtime `RandomStruct(0)` probabilistic rule. See `docs/urban-improvement-composites.md`.
  - `extract_rural_composite_meshes()` — per-(improvement, resource) rural composites for **Group A** pairs only (`IMPROVEMENT_3D_<NAME>_<RESOURCE>.png`). Bakes the per-resource merged prefab once — Mine_gold, Farm_Barley, Grove_Wine, etc. (from `aeResourceAssetVariation`) — including the prefab's own PVT splat planes (wheat field, mine excavation patch). No biome hex; per-ankh layers terrain underneath. 23 PNGs. **Group B pairs (Pasture+animal, Camp+animal — 9 pairs) are discovered by `load_rural_composite_pairs()` but deferred at render time** — they require sampling the Mecanim muscle clip to pose the herd rigs upright, which we haven't implemented. Per-ankh continues to draw bare improvement + bare resource for those tiles. See `docs/rural-improvement-composites.md` for the deferral reasoning.
  - Auto-detects game installation path on macOS and Windows.

- **`asset_index.py`**: Pure-Python parser for the game's XML asset chain (`improvement.xml` → `assetVariation.xml` → `asset.xml`, plus DLC variants). `load_improvement_assets()` returns one `ImprovementAsset` per unique `zIconName` from improvement.xml; `load_capital_assets()` does the same for `ASSET_VARIATION_CITY_*_CAPITAL` entries; `load_urban_assets()` for per-nation `ASSET_<NATION>_URBAN`; `load_resource_assets()` walks `resource.xml` for tile resources (Horse, Sheep, Wheat, Iron, …). All four return the same `ImprovementAsset` shape so callers can use one render pipeline. `load_urban_renderable_improvements()` filters to improvements eligible for urban-tile composite rendering (bUrban=1 + TerrainValid resolves to TERRAIN_URBAN + not scenario-gated), capturing `<NationPrereq>` (and `<DynastyPrereq>` mapped through a small table) — used by the urban-composite extractor. `load_rural_composite_pairs()` discovers per-(improvement, resource) rural composite pairs from `improvementClass.xml`'s `abResourceValid` table, returning `RuralCompositePair` records that distinguish Group A (per-resource merged prefab via `aeResourceAssetVariation`) from Group B (improvement prefab + separate resource prefab). No UnityPy dependency.

- **`terrain_clutter_splat.py`**: `TerrainClutterSplat` MonoBehaviour decoder, prefab walker, and per-channel mask compositor (3-channel image: R=Trees, G=MinorBuildings, B=MajorBuildings, gated by the `clear*` flags).

- **`typetree.py`**: TypeTreeGenerator setup — `setup_typetree_generator(env)` attaches a `TypeTreeGenerator(unity_version)` (loaded from `Assembly-CSharp.dll` under the game's `Managed/` dir) to the env so UnityPy's `obj.read_typetree()` works on every MonoBehaviour. Lazy-initialized inside `decode_monobehaviour(env, obj, class_name)`. The four MonoBehaviours we decode (`ClutterTransforms`, `TerrainHeightSplat`, `TerrainTexturePVTSplat`, `TerrainClutterSplat`) each have a `parse_<name>(env, obj) -> dataclass` adapter in their respective module — fields land in PascalCase from the typetree dict, the adapters remap to our snake_case dataclasses. Replaces the old hand-parse + body-budget-assert pattern; layout drift now fails loudly via `KeyError` on a missing/renamed field rather than a byte-count mismatch. See `docs/typetree-migration.md` for the migration history.

- **`clutter_culling.py`**: `RandomStruct` port (Park-Miller LCG from `decompiled/Mohawk.SystemCore/RandomStruct.cs`) + `cull_clutter_against_masks(typed_parts, mask_planes, env)`. Replicates the runtime `ClutterTransformsBackgroundData.PopulateRenderData` cull rule: per instance, sample mask at world XZ for the instance's `TerrainClutterType` channel, drop if value > `RandomStruct(0).next_float()`. Used by the urban-composite extractor.

- **`prefab.py`**: Unity GameObject/Transform tree walker. Key functions:
  - `walk_prefab(root_go)` — recurse the tree, collect MeshFilter leaves with baked world matrices
  - `bake_to_obj(parts, *, pre_rotation_y_deg=0.0)` — emit a combined OBJ string in OpenGL right-handed space (handles Unity's left-handed Y-up). The extractor passes 180° to flip authored-facing-`-Z` buildings around so they face our +Z camera.
  - `find_diffuse_for_prefab(parts)` — multi-format texture resolver (HDRP `_BaseColorMap` → URP `_BaseMap` → legacy `_MainTex`)
  - `find_ground_y(parts)` — sample the world Y of the prefab's `SplatHeightDefault` plane (the game's true ground line); used as the plinth cut height
  - `drop_splat_meshes(parts)` — filter splat-shader meshes by material name (`Splat*` / `LakeWater*` prefix + `WaterNoFoam` + `BathWater`); replaces older mesh-name-only filter
  - `strip_plinth_from_obj(obj_str, *, cut_y_override=None)` — post-process to remove baked stone foundation slabs. Two paths: when `cut_y_override` is provided (typically from `find_ground_y`), cut at that Y with two safety guards (max 65% of extent, max 50% of vertex count); otherwise fall back to a density-based heuristic.

- **`renderer.py`**: `render_mesh_to_image()` with `force_upright=True` for buildings (45° FOV, 30° tilt) and free-camera mode for units. Uses moderngl headless OpenGL.

- **`atlas.py`**: `generate_atlases()` packs categorized sprites into texture atlases for map rendering. Local use only, not part of the deployed gallery.

- **`gallery.py`**: Contains `generate_gallery()` which builds an interactive HTML gallery with search and lightbox viewing.

- **`cli.py`**: Entry points for CLI commands: `pinacotheca` (with `--no-meshes` flag to skip 3D extraction), `pinacotheca-web`, `pinacotheca-web-build`, `pinacotheca-deploy`, `pinacotheca-gallery`, `pinacotheca-atlas`.

### Key Design Patterns

- **Regex-based categorization**: The `CATEGORIES` dict maps category names to regex patterns. Patterns are checked in order—first match wins—so more specific patterns must precede general ones. Patterns are pre-compiled at module load.

- **Platform detection**: `find_game_data()` auto-detects macOS vs Windows Steam installation paths for Old World.

- **Memory management**: Extraction uses `gc.collect()` every 500 sprites and explicitly deletes image data to handle the ~4000+ sprites without memory issues.

### Output Structure

```
extracted/
├── index.html        # SvelteKit gallery (primary)
├── _app/             # SvelteKit assets (JS, CSS)
├── robots.txt        # Search engine config
└── sprites/
    ├── portraits/      # Character portraits by nation
    ├── units/          # Military unit icons
    ├── crests/         # Nation/family emblems
    ├── improvements/   # IMPROVEMENT_3D_*.png (buildings, capitals, urban tiles)
    ├── resources/      # RESOURCE_3D_*.png (tile resources — animals, crops, ores)
    └── ...             # ~40 categories total
```

## Testing

Tests are split across four files (165 tests total):
- `tests/test_categories.py` — categorization regex patterns (~95 tests)
- `tests/test_atlas.py` — atlas packing logic
- `tests/test_prefab.py` — prefab math (TRS, normal transform, X-flip, winding), splat filter, plinth strip (incl. `cut_y_override` safety guards), `find_ground_y` helpers, `bake_to_obj` `pre_rotation_y_deg` flip
- `tests/test_asset_index.py` — XML chain parsing (SingleAsset, aiRandomAssets, DLC merge, dedupe by zIconName, capital discovery)

Run with:

```bash
pytest -v
```

## Category Regex Patterns

When adding new categories or refining existing ones:

### Files to Update
1. **`src/pinacotheca/categories.py`** - Edit `CATEGORIES` dict (regex patterns) and `CATEGORY_INFO` dict (display names/icons)
2. **`web/scripts/generate-manifest.ts`** - Update `CATEGORY_INFO` to match Python version
3. **`tests/test_categories.py`** - Add/update tests for new patterns

### Pattern Rules
- Order matters: first matching pattern wins
- Use raw strings (r'...') for regex patterns
- The 'other' category is the catch-all at the end
- More specific patterns must precede general ones

### After Changing Categories
```bash
# 1. Run extraction (automatically removes stale category folders)
pinacotheca

# 2. Rebuild gallery
pinacotheca-web-build
```

The extractor automatically cleans up sprite folders that no longer match valid category names, then re-extracts those sprites to their correct new categories.

## GitHub Pages Deployment

The gallery is deployed to the `gh-pages` branch using `ghp-import`. The workflow:

1. `pinacotheca` — extract sprites locally (requires game installed)
2. `pinacotheca-web-build` — build the SvelteKit gallery into `extracted/`
3. `pinacotheca-deploy` — push `extracted/` to `gh-pages` branch

GitHub Pages serves from the `gh-pages` branch. Only sprites (~500MB) are deployed, not textures (~2GB).

## Versioning

Version is defined in `pyproject.toml` and read at runtime via `importlib.metadata`. To bump:

```bash
python scripts/bump-version.py 1.2.0  # Updates pyproject.toml + CHANGELOG.md
git commit -am 'Bump version to 1.2.0'
git tag v1.2.0
```

## Web Gallery Features

The SvelteKit gallery (`web/`) provides:
- **Search** with autocomplete dropdown
- **Category navigation** with sprite counts
- **Dimension filters** (min/max width/height, aspect ratio)
- **Lightbox** with download button and keyboard navigation
- **Shareable URLs** (`?q=archer&cat=units&minW=64`)
- **Greek pottery color scheme** (terracotta on black)

## 3D Improvement Extraction

The improvement list is **discovered from the game's XML chain at runtime** — no curated list to maintain. New improvements added by the game (DLC, patches) get extracted automatically. See `docs/improvement-naming-alignment.md` for the design and `docs/extracting-3d-buildings.md` for the splat-Y plinth + camera flip details.

### How discovery works

Three XML files are walked, then per-prefab the asset bundle is queried by GameObject name:

```
improvement.xml    → IMPROVEMENT_X (zIconName) → AssetVariation: ASSET_VARIATION_IMPROVEMENT_X
assetVariation.xml → ASSET_VARIATION_IMPROVEMENT_X → SingleAsset: ASSET_IMPROVEMENT_X
asset.xml          → ASSET_IMPROVEMENT_X → zAsset: Prefabs/Improvements/Y
```

Output PNG: `IMPROVEMENT_3D_{zIconName.removeprefix("IMPROVEMENT_")}.png`. The `prefab_name` (last path component, `Y`) is passed to `find_root_gameobject` to walk the prefab.

`load_capital_assets()` adds nation capitals (which aren't in `improvement.xml`) by scanning `ASSET_VARIATION_CITY_*_CAPITAL` entries in the same chain.

DLC content is loaded from sibling files (`improvement-event.xml`, `assetVariation-eoti.xml`, `asset-btt.xml`, etc.). Missing DLC files are silently skipped; new DLC files just need to be added to the file lists in `asset_index.py`.

### Adding things outside the XML chain

The `SUPPLEMENTAL_PREFABS` list in `extractor.py` is for prefabs not represented in `improvement.xml` (currently only the four pyramid construction stages). Format: `(prefab_root_gameobject_name, output_name)`.

### Splat-shader filter

Prefabs ship with `Plane`/`Quad`/custom-named meshes that use Old World's terrain splat shaders (heightmap, alphamap, water surfaces). Through our standard textured-mesh shader they render as broken colored plates. `drop_splat_meshes()` filters them by material name (matches `Splat*`/`LakeWater*` prefixes + exact `WaterNoFoam`/`BathWater`). If a new prefab introduces a new splat or water material name, add the prefix/exact match to `SPLAT_MATERIAL_PREFIXES` or `SPLAT_MATERIAL_EXACT` in `prefab.py`.

### After re-rendering

```bash
pinacotheca           # Re-extracts; auto-removes stale PNGs whose names don't match the new canonical set
pinacotheca-web-build # Rebuild manifest if running the SvelteKit gallery
```

To re-render a specific improvement after a fix, delete its PNG first:
```bash
rm extracted/sprites/improvements/IMPROVEMENT_3D_LIBRARY.png
pinacotheca
```

### Sparse capitals + urban tiles via ClutterTransforms

The 7 sparse base-game capitals (Greece, Rome, Persia, Carthage, Babylonia, Assyria, Egypt), every per-nation urban tile, and several improvements (Farm, Mine, Pasture, Camp, Grove, City_Site, Outpost_Ruins) carry their visible 3D content in a `ClutterTransforms` MonoBehaviour rather than a `MeshFilter` tree. `src/pinacotheca/clutter_transforms.py` decodes the MonoBehaviour body via the typetree path (see `typetree.py`), expands each `(model, instance)` pair into a `PrefabPart` at `parent_world @ instance.TRS`, and feeds the same `bake_to_obj` + `render_mesh_to_image` pipeline as everything else. See `docs/runtime-composed-cities.md` for the field layout and investigation history; `docs/typetree-migration.md` for the migration that replaced the hand parser.

### What's NOT extracted

The PVT (procedural virtual texturing) terrain layer — per-nation dirt patterns under the cities (Greek mosaics, Egyptian sand patches, etc.) — is deferred. It paints the ground beneath the buildings but the architectural identity comes from the clutter, which renders without it. See the PVT-splat investigation section in `docs/runtime-composed-cities.md` for the verified field layouts if anyone picks this up.

## Sibling Tools That Read `extracted/`

Two tools we maintain read `extracted/sprites/` directly (no manifest, just filesystem scan). Both are ours, so changes that affect filenames, directory structure, or embedded-ground rules are coordinated edits across both repos — not API breakages to negotiate around. Track the rules below so a change here doesn't silently break the lookup there.

- **per-ankh** (hex-based map renderer) — bakes our `IMPROVEMENT_3D_*.png` (and now `RESOURCE_3D_*.png`) outputs into atlases for its map view. Looks up improvements by `(tile.improvement, owner.family)` and resources by `tile.resource`, keyed on the game's canonical `zIconName`. Filenames match canonical zIconName directly.
- **SvelteKit gallery** (`web/`) — `generate-manifest.ts` scans `extracted/sprites/` at build time and emits `manifest.json`. New PNGs auto-appear; no code changes needed.

**Filename conventions per-ankh looks up**: `extracted/sprites/improvements/IMPROVEMENT_3D_<NAME>.png`, `extracted/sprites/improvements/IMPROVEMENT_3D_<NAME>_<NATION>_URBAN.png` (urban-improvement composites — see "Urban-improvement composites" below), `extracted/sprites/improvements/IMPROVEMENT_3D_<NAME>_<RESOURCE>.png` (rural-improvement composites — see "Rural-improvement composites" below), and `extracted/sprites/resources/RESOURCE_3D_<NAME>.png`, all keyed on canonical zIconName. If you rename a family or restructure directories here, update per-ankh's lookup in the same change. The naming-alignment doc proposes aligning all names to canonical zIconName in one pass when it's worth doing.

**Rural-improvement composites do NOT embed a biome hex (transparent bg around the prefab footprint).** `IMPROVEMENT_3D_<NAME>_<RESOURCE>.png` outputs render an improvement composed in 3D with the resource baked into the merged prefab — Mine+Gold with deposits worked into the structure, Farm+Barley with the wheat field painted under the buildings, etc. Per-ankh prefers `(tile.improvement, tile.resource)` lookup over the standalone improvement+resource pair render when the composite exists; falls back to drawing `IMPROVEMENT_3D_<NAME>.png` + `RESOURCE_3D_<NAME>.png` separately otherwise. Per-ankh MUST continue drawing the `TERRAIN_3D_<biome>_<height>.png` tile underneath these composites — they're biome-agnostic. The prefab's own `TerrainTexturePVTSplat` planes (the field paint, mine excavation patch) ARE baked in since they're intrinsic to the improvement's identity, not generic biome ground; the painting is transparent outside the painted area, so per-ankh's biome hex still shows around it. Sidecar tag is `composition: "layered"` whenever PVT planes were composed (most rural composites — only NETS variants lack them), but the bbox is still tile-sized so per-ankh's relative-scaling logic against bare prefab outputs is fine. **Pasture+animal and Camp+animal pairs are NOT in this set** — animal-rig idle pose data lives in compressed Mecanim muscle clips that we don't currently sample, so those 9 pairs (Pasture+HORSE/CATTLE/SHEEP/PIG/GOAT, Camp+CAMEL/ELEPHANT/FUR/GAME) fall back to the bare-improvement + bare-resource render path in per-ankh. 23 PNGs in this set. See `docs/rural-improvement-composites.md`.

**Urban-improvement composites embed ground + the surrounding nation urban tile.** `IMPROVEMENT_3D_<NAME>_<NATION>_URBAN.png` outputs render the improvement nestled inside the nation's urban tile — biome (TEMPERATE) + per-nation PVT paint + culled urban clutter + the improvement on top, matching the in-game runtime composition (`ClutterTransformsBackgroundData.cs:158-162` probabilistic culling against the improvement's `TerrainClutterSplat` mask). Per-ankh looks up `(tile.improvement, tile.urban_nation)` and prefers this composite over the standalone `IMPROVEMENT_3D_<NAME>.png` when both exist. Universal urban improvements (Library, Forum, Theater, etc.) are rendered on each of the 10 urban-tile nations; nation-locked improvements (52 shrines + Aksumite/Persian/Egyptian wonders) are rendered only on their own nation. ~750 PNGs total. See `docs/urban-improvement-composites.md` for the design.

**Capital + urban + generic-city PNGs embed ground.** As of the layered-render work, `IMPROVEMENT_3D_<NATION>_CAPITAL.png` (12 nations), `IMPROVEMENT_3D_<NATION>_URBAN.png` (10 nations), and the two generic-city outputs `IMPROVEMENT_3D_CITY.png` and `IMPROVEMENT_3D_CITY_SITE.png` include a `TERRAIN_TEMPERATE` biome hex tile + their `TerrainTexturePVTSplat` paint underneath the buildings. The generic-city additions follow the same rule: per-ankh does not draw terrain under those tiles either, and both prefabs are sparse enough (compound walls with bare ground between buildings, stockade ring with gaps between hovels) that without painted ground showing through, the gaps stay empty. Per-ankh must NOT double-render terrain underneath any of these — the hex ground is part of the icon. All other `IMPROVEMENT_3D_*.png` outputs (regular improvements, supplemental prefabs) and `RESOURCE_3D_*.png` outputs are unchanged: still transparent backgrounds. The set of layered prefabs is defined by `GENERIC_LAYERED_Z_ICONS` in `extractor.py` plus all capitals/urbans from the XML chain. See `docs/extracting-3d-buildings.md` (Ground layer section) and `src/pinacotheca/layered_render.py` for the design.

**3D terrain tiles are rendered as standalone (biome × height) PNGs and embed ground.** `extracted/sprites/terrains/TERRAIN_3D_<BIOME>_<HEIGHT>.png` covers the full canonical 28-tile set: 6 land biomes × 4 heights (TEMPERATE/LUSH/ARID/SAND/TUNDRA/MARSH × FLAT/HILL/MOUNTAIN/VOLCANO) + URBAN_FLAT + WATER × {COAST, OCEAN, LAKE}. Per-ankh looks these up by `(tile.biome, tile.height)` and must NOT draw any terrain layer underneath — like capitals/urbans/generic-city, the hex ground is part of the icon. Outputs are tagged `composition: "layered"`. HILL/MOUNTAIN/VOLCANO have **real 3D peak geometry**: the prefabs ship as flat Quads, but the runtime's `TerrainHeightSplat` vertex shader is replicated offline by `terrain_height_splat.tessellate_displaced_obj` (CPU-tessellate the Quad to 64×64, sample the heightmap R-channel at each UV, displace world Y by `R × intensity` per the parsed MonoBehaviour fields). Mountains pick a biome-appropriate PVT plane (Snow/Arid/Grass) for the peak texture. Water tiles render the seabed PVT (no biome ground); the water-shader surface (`WaterWithFoam`) is procedurally shaded in-game and not fully reproducible offline — this is a known limitation, the tiles are still visually distinguishable. See `src/pinacotheca/terrain_index.py` (chain walker), `src/pinacotheca/terrain_height_splat.py` (parser+tessellation), and `src/pinacotheca/terrain_render.py` (orchestrator).

**All 3D outputs go through richer material rendering.** The shader now applies tangent-space normal mapping (DXT5nm-decoded `_BumpMap`), occlusion modulation (B channel of `_MetalicRoughnessOcclusionTeamColor`, strength 0.6), and pre-process pink-to-neutral team-color replacement on diffuse textures. Effects apply to every render that uses the buildings shader path — `IMPROVEMENT_3D_*`, `UNIT_3D_*`, and `RESOURCE_3D_*`. Outputs across the catalog look brighter, more defined at the surface (brick/stair/cornice detail), and free of pink "team-color" placeholder artifacts. No filename or shape changes; only pixel content. See `docs/material-rendering.md` for the shader detail and tuning knobs.

**Every 3D PNG ships with a JSON metadata sidecar** at the same stem (`IMPROVEMENT_3D_LIBRARY.png` ↔ `IMPROVEMENT_3D_LIBRARY.json`). Schema is versioned (`"version": 1`) and lives in `src/pinacotheca/render_metadata.py`. Exposes `world.maxExtent`, `world.bboxMin/Max`, the camera framing constants used for the render, and `render.worldUnitsPerOutputPixel` for absolute pixel placement. Per-ankh uses these to scale a resource sprite over a rural improvement (Camp/Pasture/Mine/Quarry/Lumbermill) at correct relative size — without the sidecar each PNG is rendered tight to its own bbox, so the herd dwarfs the fence on a Pasture-with-Horse tile. Layered outputs (capitals, urbans, generic-city, urban-improvement composites) are tagged `composition: "layered"` and their bbox covers the whole composited scene; per-ankh should not relative-scale layered icons against per-prefab ones. Sidecars are excluded from the gh-pages deploy via `GALLERY_EXCLUDE_GLOBS` (gallery only displays PNGs; per-ankh consumes `extracted/` locally). See `docs/extracting-3d-buildings.md` "Metadata sidecar" for the full schema.

### Gallery deploy filter

Some sprite categories are present locally for per-ankh but excluded from the gh-pages deploy and the SvelteKit manifest, because the deployed site is bound by GitHub Pages' 1 GB cap. The filter list lives in `src/pinacotheca/gallery_filter.py` (`GALLERY_EXCLUDE_GLOBS`) — Python is the source of truth; the TS-side `web/scripts/generate-manifest.ts` reads a JSON sidecar (`extracted/.gallery-filter.json`) that `pinacotheca` writes after extraction. Both sides fail hard if the sidecar is missing while sprites are present (no silent fallbacks defeating the cap).

Currently excluded: per-(improvement, nation) urban composites (`improvements/IMPROVEMENT_3D_*_*_URBAN.png`, ~1.3 GB / 719 files), and the per-render JSON metadata sidecars (`improvements/*.json`, `resources/*.json`, `units/*.json`) — sidecars are consumed by per-ankh from the local tree and aren't useful in the deployed gallery. **per-ankh continues to read `extracted/sprites/` directly and is unaffected by the filter** — this is the load-bearing invariant of the design. Pattern contract: only `*` wildcards (no `?`, `[...]`, `**`); `*` does not cross `/`. Validated at module load. The Python matcher in `gallery_filter.py:_compile_glob` translates `*` to `[^/]*` (stricter than stdlib `fnmatch.fnmatchcase`, which would let `*` cross `/`); parity with the TS-side regex translation is verified by `tests/test_gallery_filter.py::TestPythonTSParity`.

The deploy command stages `extracted/` to a temp dir via `rsync -aL --copy-unsafe-links --exclude=sprites/<glob>`, then optionally runs `oxipng -o 2 --strip safe -t <cores> -r --preserve` for ~7-10% additional compression. `-o 2` (oxipng default) was chosen over `-o 4` after benchmarking — the higher level gave only +0.3 percentage points of savings at 3× the runtime on these renders. `extracted/` itself is never modified — staging is a deploy-time view. `oxipng` and `rsync` are soft deps (rsync is required; oxipng is skipped with a warning if missing).

To change the filter: edit `GALLERY_EXCLUDE_GLOBS` and re-run `pinacotheca`. To inspect filtered files: browse `extracted/sprites/` directly. CLI flags: `--no-optimize` skips oxipng, `--no-filter` is an emergency override that deploys everything (warns it'll exceed the cap).

### Mod extraction + artist opt-outs

Pinacotheca scans `~/Library/Application Support/OldWorld/Mods/` (macOS) for installed Old World mods and extracts each one's Unity AssetBundles alongside the base-game extraction. 3D bundles run through the existing prefab walker + renderer (rendered in both `_FRONT` and `_BACK` views since mod authors don't share a canonical facing direction); 2D bundles iterate `Sprite`/`Texture2D` objects. Outputs land under `extracted/sprites/mods/<slug>/<sub>/*.png` with a per-mod `mod.json` sidecar. See `docs/mod-extraction.md` for the full design, attribution table, and the 2D `Sprite` → `Texture2D` fallback (Greek Dynasties' resource bundle hits a UnityPy sprite-crop bug that returns blank images).

Per-sprite attribution is driven by `_MOD_ATTRIBUTION` in `src/pinacotheca/mod_extractor.py` — the `<author>` field in ModInfo is the primary credit, but collaborators (e.g. "And" credited for Dynamic Unit icons, "Revan" for Greek Dynasties' resource icons, "Shirotora Kenshin" for Maniac's bundled 3D sword) are tracked there explicitly. Each entry resolves to `{"default": [...], "overrides": [{"pattern": regex, "authors": [...]}]}` and is written into the mod's `mod.json` so the TS-side `generate-manifest.ts` can stamp per-sprite `authors: string[]` without re-parsing the description.

**Publication approval (per-mod allowlist)**: `APPROVED_AUTHORS_BY_MOD` (also in `mod_extractor.py`) is a `dict[str, frozenset[str]]` mapping mod slug → set of authors approved to publish *that specific mod's* images in the deployed gallery. A sprite ships only when its mod has an entry AND every credited author is in that mod's approved set. The per-mod shape matches how approval actually works (artists say "yes, for this mod") and protects against future mods slipping through just because they happen to credit names approved elsewhere. Sprites with empty author lists (e.g. Dynamic World, where ModInfo `<author>` is empty and we have no `_MOD_ATTRIBUTION` entry) are filtered too — "no one to ask" doesn't count as approval. Files still get rendered locally — important load-bearing invariant: the user with the mod installed retains every file for per-ankh / Finder / local inspection. At sidecar-write time, `compute_excluded_mod_globs()` walks each mod's `mod.json`, resolves per-file authors against the attribution table, and emits literal-path globs for sprites that aren't cleared. These get merged into the standard gallery-filter sidecar via the `extra_globs` param on `write_filter_sidecar()` — the same mechanism that excludes urban composites from deploy and manifest. `deploy()` reads the sidecar's `excludeGlobs` (merged list), not the static `GALLERY_EXCLUDE_GLOBS` constant. Mods whose entire sprite set gets filtered (`count = 0` after manifest scan) are auto-dropped from the gallery's Mods section by `scanMods` in `generate-manifest.ts`. To grant/revoke approval: edit `APPROVED_AUTHORS_BY_MOD` and rerun `pinacotheca-mods` to regenerate the sidecar.
