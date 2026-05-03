# Changelog

## [Unreleased]

## [2.4.0] - 2026-05-02

### Added
- 3D vegetation tile renders covering trees, scrub, jungle, and their
  cut/charred/charred_minor/hurricane variants:
  `extracted/sprites/vegetation/VEGETATION_3D_<NAME>.png`. 43 outputs
  total, spanning the full cross product of vegetation type ×
  (terrain | height | state). Layered composition (biome ground +
  per-prefab PVT splat + clutter on top), tagged
  `composition: "layered"`. Discovery is variation-driven — every
  `ASSET_VARIATION_VEGETATION_*` entry is scanned and the suffix
  parses into `(terrain_z_type, height_z_type)` for biome ground
  lookup; `aiRandomAssets` candidates expand into separate `_NN`
  outputs (jungle, trees) deduped by prefab name within each
  variation. New asset_index function `load_vegetation_assets`. New
  extractor entry point `extract_vegetation_meshes`, wired into the
  standard `pinacotheca` run between `extract_terrain_tiles` and the
  end of the pipeline.
- `cull_back: bool = True` kwarg on `render_mesh_to_image` and
  `render_layered_ground` (buildings layer only). Vegetation passes
  `cull_back=False` so 4-vert quad billboards with random Y rotation
  don't lose ~half their instances to back-facing slivers — Old World
  authors trees as static quads with stochastic rotations and relies
  on double-sided alpha-cutout shaders at runtime; we reproduce the
  same behavior offline.
- `apply_texture_mask: bool = True` kwarg on
  `clutter_spawner_to_prefab_parts`. Default keeps the existing
  resource-prefab behavior (Iron, Gem, etc. cluster per the authored
  per-tile mask). Vegetation passes `apply_texture_mask=False` to
  spread instances uniformly via raw Halton — a forest icon should
  fill the hex, not cluster in one corner. The `rng.next_float()`
  color-lerp call is still drawn to keep the random sequence aligned
  with the runtime.
- New "Vegetation" category (`vegetation/`) with regex `^VEGETATION_`.
  Display info added in both `categories.py` and the TS-side
  `web/scripts/generate-manifest.ts` for SvelteKit gallery parity.

### Known limitations
- HILL height variants render on a flat hex for v1; the 3D peak
  feature stacking (already implemented for `extract_terrain_tiles`)
  is not yet plumbed into the vegetation extractor.
- Per-instance color jitter (`minColor`/`maxColor` in
  `ClutterSpawner.Model`) is consumed for RNG alignment but not
  applied — vegetation's autumn-leaf variation is omitted. Plumbing
  per-instance vertex color through `bake_to_obj` and the shader is
  deferred.

## [2.3.0] - 2026-05-01

### Added
- 3D terrain tile renders covering the canonical 28-tile set:
  `extracted/sprites/terrains/TERRAIN_3D_<BIOME>_<HEIGHT>.png` for 6
  land biomes (TEMPERATE / LUSH / ARID / SAND / TUNDRA / MARSH) × 4
  heights (FLAT / HILL / MOUNTAIN / VOLCANO) plus URBAN_FLAT and
  WATER × {COAST, OCEAN, LAKE}. HILL / MOUNTAIN / VOLCANO carry real
  3D peak geometry: the prefabs ship as flat Quads, but the runtime
  `TerrainHeightSplat` vertex displacement is replicated offline as
  CPU tessellation in `terrain_height_splat.tessellate_displaced_obj`
  (sample heightmap R-channel at each UV, displace world Y by
  `R × intensity`). Mountains pick a biome-appropriate PVT plane
  (Snow / Arid / Grass) for the peak texture; water tiles render the
  seabed PVT with a sky-tint × transmittance blend. New modules
  `terrain_index.py` (chain walker), `terrain_height_splat.py`
  (parser + tessellation), `terrain_render.py` (orchestrator). Wired
  into the standard `pinacotheca` run. Outputs are tagged
  `composition: "layered"`. Per-ankh looks these up by
  `(tile.biome, tile.height)` and must not draw a separate terrain
  layer underneath.
- Per-render JSON metadata sidecar next to every 3D PNG output
  (`IMPROVEMENT_3D_*`, `RESOURCE_3D_*`, `UNIT_3D_*`, layered tiles).
  Schema lives in new module `src/pinacotheca/render_metadata.py`
  (`version: 1`, camelCase keys). Exposes `world.maxExtent`,
  `world.bboxMin/Max`, the camera framing constants, and
  `render.worldUnitsPerOutputPixel` — the last accounts for both the
  autocrop and the LANCZOS upscale `autocrop_with_padding` applies when
  cropped content is below `min_size`. Layered outputs are tagged
  `composition: "layered"` (capitals, urbans, generic-city,
  per-(improvement, nation) urban composites); standalone outputs are
  `"prefab"`. Closes #4. See `docs/extracting-3d-buildings.md`
  "Metadata sidecar" for the full schema and per-ankh's intended
  consumption pattern.
- `world.groundHex` on layered sidecars: world-space `bboxMin/Max` of
  the visible inscribed ground hex plus `pixelBboxMin/Max` — the same
  rectangle in output PNG pixel coordinates, derived from the biome
  layer's alpha after autocrop + LANCZOS upscale. Per-ankh anchors
  hex-clip cells to this rectangle directly with no projection math,
  resolving the transparent-apex artifact (issue #5) on tall
  buildings whose bbox extended above the ground hex. Additive — the
  field is `null` on prefab sidecars and the schema version is
  unchanged.
- Auto-brighten unusually-dark diffuse textures
  (`prefab.apply_auto_luminance_compensation`). Yazilikaya's diffuse
  was authored ~4× darker than peer wonders — the in-game HDRP
  pipeline lifts it via tone mapping + exposure + indirect ambient,
  but our offline renderer treats sRGB textures as display-ready.
  The new pre-process is threshold-gated (mean BT.601 luminance over
  `alpha > 128` pixels < 70 → scale RGB toward 130, clamped to 255);
  Library / Granary / Acropolis / Hanging Garden / Pyramid measure
  above the threshold and pass through bit-identical.

### Changed
- Camera tilt switched 30° → 45° to match the in-game main camera
  (`GameCamera.cs:52-56`, used at every zoom level). Aligns rendered
  hex shapes on layered tiles with what the game shows on a single
  tile. The 30° value pre-dated decompiled-source verification.
- MonoBehaviour decode now routes through `TypeTreeGenerator` (new
  `typetreegeneratorapi` dependency, new `src/pinacotheca/typetree.py`)
  instead of four hand-rolled binary parsers for `ClutterTransforms`,
  `TerrainTexturePVTSplat`, `TerrainHeightSplat`, and
  `TerrainClutterSplat`. Per-class adapter functions remap the
  resulting PascalCase typetree dicts into our existing snake_case
  dataclasses, so call sites stay unchanged. Layout drift now fails
  loudly with `KeyError` on a missing/renamed field rather than a
  body-budget mismatch. Bit-for-bit parity validated against all
  1417 MonoBehaviour instances in the current build (140
  `ClutterTransforms`, 538 `TerrainHeightSplat`, 437
  `TerrainTexturePVTSplat`, 302 `TerrainClutterSplat`). See
  `docs/typetree-migration.md`.
- `render_mesh_to_image` and `render_layered_ground` return
  `(Image, RenderMetadata)` tuples instead of bare `Image`. All
  internal call sites updated; this is a public API change to the
  exported renderer entry point.
- `autocrop_with_padding` now returns
  `(image, cropped_dims_pre_upscale, crop_origin)` — the second
  element gives cropped dimensions before the min-size LANCZOS
  upscale (so callers can derive `worldUnitsPerOutputPixel`); the
  third gives the post-padding crop origin in input-image pixel
  coordinates (so layered_render can map biome-alpha pre-crop coords
  into output PNG pixel coords for `groundHex.pixelBboxMin/Max`).
- `gallery_filter.matches_filter` now uses an inline glob→regex
  translator (`_compile_glob`) instead of `fnmatch.fnmatchcase`. The
  stdlib version lets `*` cross `/`, which silently broadened patterns
  like `improvements/*.json` to also match
  `improvements/sub/foo.json` and diverge from the TS-side
  `globToRegExp`. The new compiler matches TS behavior; the parity
  test in `tests/test_gallery_filter.py` was updated to compare the
  Python compiler against the TS regex (no longer fnmatch). Behavior
  for the existing single-`*` patterns is unchanged.
- `GALLERY_EXCLUDE_GLOBS` extended to drop JSON sidecars
  (`improvements/*.json`, `resources/*.json`, `units/*.json`) from the
  gh-pages deploy. Sidecars are consumed by per-ankh from the local
  tree; the deployed SvelteKit gallery only displays PNGs.

### Documentation
- `docs/typetree-migration.md` (new) — migration plan and history
  for replacing hand-parsed MonoBehaviours with `TypeTreeGenerator`.
- `docs/typetree-spike-findings.md` (new) — investigation notes from
  the typetree spike.

## [2.2.0] - 2026-04-30

### Added
- `RESOURCE_3D_*.png` outputs in `extracted/sprites/resources/` for 32 tile
  resources via `asset_index.load_resource_assets()`. Each prefab produces
  `_SOLO` (artist rig) and `_HERD` (in-game default) variants, with rig-family
  splits for Crab and Fish. 21/32 render today; 11 (Iron, Gold, Gem, Silver,
  Barley, Sorghum, Wheat, Honey, Lavender, Olive, Wine) await `ClutterSpawner`
  support.
- Per-(improvement, nation) urban-tile composites:
  `IMPROVEMENT_3D_<NAME>_<NATION>_URBAN.png` (~750 outputs). Replicates the
  in-game composition: `TERRAIN_TEMPERATE` biome + per-nation PVT paint +
  culled urban clutter + improvement on top, with `RandomStruct(0)` Park-Miller
  cull matching `ClutterTransformsBackgroundData.PopulateRenderData`. New
  `clutter_culling.py`, `terrain_clutter_splat.py`,
  `load_urban_renderable_improvements()`. See
  `docs/urban-improvement-composites.md`.
- Layered ground rendering for capitals (12), urban tiles (10), and generic
  city prefabs (`IMPROVEMENT_3D_CITY.png`, `IMPROVEMENT_3D_CITY_SITE.png`).
  Composes biome base + per-prefab `TerrainTexturePVTSplat` paint under the
  buildings via new `layered_render.py`, `biome_base.py`, `pvt_splats.py`.
- Tangent-space normal mapping (DXT5nm-decoded `_BumpMap`), occlusion
  modulation (B channel of `_MetalicRoughnessOcclusionTeamColor`, strength
  0.6), and pink-to-neutral team-color replacement on diffuse textures —
  applied across `IMPROVEMENT_3D_*`, `UNIT_3D_*`, `RESOURCE_3D_*`. See
  `docs/material-rendering.md`.
- Gallery deploy filter (`gallery_filter.py` + `.gallery-filter.json`
  sidecar): per-(improvement, nation) urban composites stay local for
  per-ankh but are excluded from the gh-pages deploy to stay under the
  GitHub Pages 1 GB cap. Deploy now stages via rsync to a temp dir and
  runs an optional `oxipng -o 2` pass before `ghp-import`.

### Changed
- `extract_improvement_meshes` job tuple expanded from
  `(prefab, output_name)` to `(prefab, output_name, output_dir,
  filename_prefix)` so resources can route to a separate output bucket.
  Stale-PNG cleanup tracks per (dir, prefix).
- Renderer: `bbox_override` parameter shares one camera across layered
  passes; `flat_lighting` flag for ground layers; `parse_obj` /
  `bake_to_obj` carry tangents through a custom `vtg` OBJ extension;
  fragment shader uses `mix(0.4, 1.0, …)` for buildings (vs. prior
  `max(dot, 0.3)`) so flat ground reads at full brightness.
- Test count: 165 → 230+, with new suites for biome base, layered
  render, pvt splats, clutter culling, terrain clutter splats, team
  color, gallery filter, manifest filter, deploy.

### Fixed
- CI lint job now installs project dev deps (`pip install -e ".[dev]"`),
  so mypy resolves UnityPy-derived types and the `# type: ignore`
  comments at `prefab.py` no longer read as unused-ignore.

### Documentation
- `docs/material-rendering.md` (new) — shader pipeline reference.
- `docs/extracting-3d-resources.md` (new) — resource rendering recipes.
- `docs/urban-improvement-composites.md` (new) — composite design.
- `docs/clutter-spawner.md` (new) — investigation notes for the
  remaining clutter system.
- CLAUDE.md — `reference/` and `decompiled/` symlinks documented at
  top; downstream-consumer contract updated for embedded-ground rules
  and material rendering.

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
