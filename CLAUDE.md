# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Pinacotheca is a Python tool for extracting and cataloging sprite assets from the game **Old World** (a 4X strategy game by Mohawk Games). It uses UnityPy to extract sprites directly from Unity asset bundles without requiring external tools like AssetRipper.

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
├── __init__.py       # Package exports
├── categories.py     # Sprite categorization (regex patterns, pre-compiled)
├── extractor.py      # UnityPy extraction (sprites, units, improvements, composites)
├── prefab.py         # GameObject/Transform walker, OBJ baker, splat/plinth filters
├── renderer.py       # moderngl 3D mesh rendering with building/unit cameras
├── atlas.py          # Texture atlas generation
├── gallery.py        # HTML gallery generator (legacy)
├── cli.py            # Command-line interface entry points
└── py.typed          # PEP 561 marker for type hints

docs/                 # Investigation writeups, feature requests, references
├── extracting-3d-buildings.md
├── extracting-game-assets-from-unity-with-python.md
├── atlas-reference.md
├── improvement-naming-alignment.md       # Canonical zIconName follow-up effort
├── feature-request-per-ankh-map-atlas.md # Downstream consumer requirements
└── per-ankh-missing-improvements.md      # Gap tracking

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
```

### Key Modules

- **`categories.py`**: Defines `CATEGORIES` dict mapping category names to regex patterns. Patterns are pre-compiled for performance. The `categorize()` function returns the category for a sprite name.

- **`extractor.py`**: Three extraction entry points called in sequence by `pinacotheca`:
  - `extract_sprites()` — 2D sprite extraction (the original 4000+ icon set)
  - `extract_unit_meshes()` — 3D unit mesh renders (`UNIT_3D_*.png`)
  - `extract_improvement_meshes()` — 3D improvement renders (`IMPROVEMENT_3D_*.png`); discovers the asset list at runtime from the game's XML chain via `asset_index.py`. Includes a small `SUPPLEMENTAL_PREFABS` list for things not in `improvement.xml` (currently only the four pyramid construction stages) and `PREFAB_DECODE_BLACKLIST` for prefabs whose Texture2D decode SIGSEGVs UnityPy.
  - Auto-detects game installation path on macOS and Windows.

- **`asset_index.py`**: Pure-Python parser for the game's XML asset chain (`improvement.xml` → `assetVariation.xml` → `asset.xml`, plus DLC variants). `load_improvement_assets()` returns one `ImprovementAsset` per unique `zIconName` from improvement.xml; `load_capital_assets()` does the same for `ASSET_VARIATION_CITY_*_CAPITAL` entries (which aren't in improvement.xml). No UnityPy dependency.

- **`prefab.py`**: Unity GameObject/Transform tree walker for composite buildings. Key functions:
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
    ├── portraits/    # Character portraits by nation
    ├── units/        # Military unit icons
    ├── crests/       # Nation/family emblems
    └── ...           # ~40 categories total
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

### What's NOT extracted

7 of 12 nation capitals (Greece, Persia, Rome, Carthage, Babylonia, Assyria, Egypt) and all per-nation urban tiles use runtime PVT (procedural virtual texturing) composition that we can't reproduce in isolated PNG renders without re-implementing a chunk of the game's terrain shader. See `docs/runtime-composed-cities.md` for the full investigation and a phased implementation plan if/when this becomes worth pursuing.

## Downstream Consumer Contract

The 3D improvement renders are consumed by external tools that scan the filesystem rather than parsing a manifest:

- **per-ankh** (hex-based map renderer) — bakes our `IMPROVEMENT_3D_*.png` outputs into atlases for its map view. Looks up by `(tile.improvement, owner.family)` keyed on the game's canonical `zIconName`. Since the XML-driven discovery work, our filenames now match canonical zIconName directly. See `docs/feature-request-per-ankh-map-atlas.md` for their requirements and `docs/per-ankh-missing-improvements.md` for the gap (we ship ~112 of their ~179 in-use improvement types).
- **SvelteKit gallery** (`web/`) — `generate-manifest.ts` scans `extracted/sprites/` at build time and emits `manifest.json`. New PNGs auto-appear; no code changes needed.

**API surface**: PNG filenames in `extracted/sprites/improvements/IMPROVEMENT_3D_<NAME>.png`. Renames are breaking changes; coordinate with per-ankh before renaming. The naming-alignment doc proposes a future major version bump that aligns all names to canonical zIconName at once.
