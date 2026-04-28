# Changelog

## [Unreleased]

## [2.1.0] - 2026-04-28

### Added
- 25 new `IMPROVEMENT_3D_*.png` outputs driven by a `ClutterTransforms`
  hand-parser (`src/pinacotheca/clutter_transforms.py`):
  - 7 sparse capitals: Greece, Rome, Egypt, Persia, Carthage, Babylonia, Assyria
  - 11 per-nation urban tiles
  - 7 improvements that turned out to be clutter-driven (previously
    classified as PVT-only): Farm, Mine, Pasture, Camp, Grove,
    City_Site, Outpost_Ruins
- `load_urban_assets()` discovers per-nation urban-tile prefabs via
  `ASSET_<NATION>_URBAN` entries in `asset.xml`
- Verbose `[CT]` log lines per prefab surfacing clutter inventory
  (model count, instance count, ClutterTransforms count) so each run
  reports which targets carry clutter

### Changed
- `extract_improvement_meshes` now loads `globalgamemanagers.assets`
  alongside `resources.assets` so MonoBehaviour script-class resolution
  works (m_Script PPtrs typically have `file_id=1`)
- `drop_splat_meshes` now also drops materialless parts (capitals'
  `*Bull` no-op `TerrainHeightSplat` placeholders with empty
  MeshRenderer materials) and no longer restores the original list
  when the filter would drop everything — with clutter augmentation in
  place, "all `MeshFilter` parts are splat or materialless" is a
  legitimate signal that the real geometry comes from
  `ClutterTransforms` rather than an over-aggressive filter

### Fixed
- Sparse capitals + urban tiles previously produced no PNG (skipped
  with "no diffuse texture in prefab materials"); now render through
  the same pipeline as every other improvement

## [2.0.0] - 2026-04-27

### Breaking
- 3D improvement PNG filenames now use canonical `zIconName` from `improvement.xml`
  (e.g. `IMPROVEMENT_3D_LIBRARY.png`). Many filenames have changed from prior versions —
  downstream consumers (per-ankh) keying on PNG paths must update their lookups.

### Added
- 3D improvement and composite mesh extraction (`extract_improvement_meshes`,
  previously curated `extract_composite_meshes` folded into the same path)
- XML-driven asset discovery via new `asset_index.py` — walks
  `improvement.xml → assetVariation.xml → asset.xml` (plus DLC variants); new
  improvements added by the game appear automatically with no code changes
- Capital extraction via `load_capital_assets()` — discovers
  `ASSET_VARIATION_CITY_*_CAPITAL` entries (5 capitals render: Maurya, Tamil,
  Yuezhi, Aksum, Hittite; Egypt renders as obelisk-only)
- `SUPPLEMENTAL_PREFABS` hook for assets outside the XML chain (the four
  pyramid construction stages)
- 3D mesh renders bumped from 1024 → 2048 with mipmaps and trilinear filtering
- Splat-plane-Y plinth cutting for buildings that sit on baked stone foundations,
  with extent + vertex-count safety guards; falls back to the prior density heuristic
- 180° Y pre-rotation in `bake_to_obj` to align Unity-authored `-Z`-facing
  buildings with the OpenGL `+Z` camera
- `--no-meshes` flag on the `pinacotheca` CLI to skip 3D extraction
- Stale-PNG cleanup at the start of 3D extraction
- `PREFAB_DECODE_BLACKLIST` to hard-skip prefabs whose Texture2D decode SIGSEGVs
  UnityPy (currently Fort)

### Changed
- 114 3D improvement renders now ship (vs. 67 in 1.1.0), all under canonical names
- `drop_splat_meshes` now filters by material name (`Splat*` / `LakeWater*`
  prefixes + exact `WaterNoFoam` / `BathWater`) instead of mesh-name only —
  catches custom-named splat meshes that previously leaked through (Watermill
  Quad, Market `MarketSplat`, Hamlet `HamletFloor`, bath water surfaces)
- Test suite expanded from 95 → 165 tests; new `test_asset_index.py` and
  greatly expanded `test_prefab.py`

### Removed
- Hand-curated `IMPROVEMENT_MESHES` and `COMPOSITE_PREFABS` lists
- Raw-mesh fallback path in extractor (`_resolve_mesh_variant`, `_find_texture`)
- Defunct probe scripts `scripts/inspect_splat_y.py` and `scripts/inspect_barracks.py`

### Documentation
- New `docs/extracting-3d-buildings.md`, `docs/runtime-composed-cities.md`
  (PVT investigation for the 7 unrendered capitals + urban tiles),
  `docs/improvement-naming-alignment.md`, `docs/feature-request-per-ankh-map-atlas.md`,
  `docs/per-ankh-missing-improvements.md`, `docs/code-review-3d-improvements.md`
- `CLAUDE.md` and `README.md` rewritten around XML-driven discovery and the
  downstream consumer contract

## [1.1.0] - 2026-04-05

- Clean up versioning, deployment, and CLI commands
- Add `pinacotheca-web` and `pinacotheca-web-build` CLI commands
- Decouple legacy HTML gallery from extraction pipeline
- Single-source version from `pyproject.toml` via `importlib.metadata`
- Remove redundant GitHub Actions deploy workflow
- Add version bump script and changelog

## [1.0.0] - 2025-01-01

Initial release.

- Extract sprites from Old World Unity asset bundles via UnityPy
- Regex-based categorization into ~40 categories
- 3D unit mesh rendering to 2D images
- SvelteKit gallery with search, filters, and lightbox
- Legacy standalone HTML gallery
- Texture atlas generation for map rendering
- Exclusion pattern support for sprite filtering
- GitHub Pages deployment via `pinacotheca-deploy`
- CI pipeline with ruff, mypy, and pytest
