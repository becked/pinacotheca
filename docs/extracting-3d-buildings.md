# Extracting 3D Building Renders from Old World

This doc records what we learned while extending Pinacotheca's 3D extraction pipeline from units only to buildings/improvements (including DLC content like Empires of the Indus).

## Goal

For each in-game improvement, wonder, and DLC capital, produce a 2D PNG render of the 3D model so it can be browsed alongside the existing 2D sprites. Output names follow the existing `IMPROVEMENT_3D_<NAME>.png` convention so they classify automatically into the `improvements` category.

## What's in the assets

`resources.assets` (1.35 GB) contains everything in one bundle — there are no DLC-specific asset files on disk. Empires of the Indus content (Maurya, Tamil, Yuezhi capitals) lives in the same single bundle as the base game.

A scan of the bundle finds:

- 3,759 `Mesh` assets total
- ~80 unit `_GEO` meshes (already handled by `extract_unit_meshes`)
- 39 cleanly named `*_LOD0` meshes for improvements (`Library_LOD0`, `ChristianTemple_LOD0`, religious shrines, civic buildings)
- ~50 named non-LOD improvements (`Academy`, `Market`, `Palace`, etc.)
- ~6 composite/prefab meshes (`Maurya_Capital`, `Tamil_Capital`, `Hanging_Garden`, etc.)
- ~2,500 procedural city-block decoration meshes (`BigHome`, `Cypress`, `MotarAndHay`, `Hut`, `Mansion`…) — out of scope; these are filler for procedural city visualizations

## Three rendering categories

Buildings split into three groups based on how they're authored, and each needs different handling.

### 1. Single-piece improvements (renders cleanly via raw mesh)

Examples: `Library_LOD0`, `ChristianTemple_LOD0`, all the religious shrines.

The mesh asset itself is a complete building. Calling `mesh_data.export()` gives a usable Wavefront OBJ that the renderer can consume directly. The artist often baked a stone plinth/foundation into the mesh — for example, `Library_LOD0`'s bottom 5% of vertical extent covers its full XZ footprint, while `Granary_LOD0`'s bottom 5% covers only ~5%.

### 2. Prefab-walked improvements (need GameObject hierarchy)

Same examples, but rendered through the prefab instead — necessary because the building's authored mesh is sometimes laid flat or scaled differently from how it appears in-game. The prefab's root Transform applies the orientation correction.

The Granary is a clear case: its raw mesh has X span 0.055, Y span 0.048, Z span 0.014 (Y looks like the up-axis but isn't reliably so). The prefab applies a world matrix with `diag=(-65.95, 0.00, -0.00)` — a 100× scale combined with a 90° rotation around X that swaps the model's up-axis to world-Y.

### 3. Composite prefabs (multiple sub-meshes assembled by transforms)

Examples: `Maurya_Capital`, `Tamil_Capital`, `Yuezhi_Capital`, `AksumCapitol`, `Hanging_Garden`, `Kushite_Pyramid`, `Ishtar_Gate33`, `Pyramid_lvl_1`–`4`.

These are GameObject trees with multiple `MeshFilter` leaves pointing to separate sub-meshes. Each sub-mesh's vertices are stored in *its own GameObject's local space*; the prefab's Transform hierarchy is what assembles them into a building. Rendering the named Mesh asset alone produces an exploded scatter — see `scripts/probes/output/Maurya_Capital.png` for the broken case before the fix.

The fix is in `src/pinacotheca/prefab.py`:

1. `find_root_gameobject(env, name)` — find a GameObject by name whose Transform has no parent.
2. `walk_prefab(root_go)` — recurse top-down, composing `m_LocalPosition`/`m_LocalRotation`/`m_LocalScale` into 4×4 world matrices, collecting `(Mesh, world_matrix, materials)` for each `MeshFilter` leaf.
3. `bake_to_obj(parts)` — apply each part's world matrix to its vertices (and `inverse_transpose(M[:3,:3])` to normals for non-uniform scale handling), then emit a single combined OBJ.
4. `find_diffuse_for_prefab(parts)` — walk all materials, probe `_BaseColorMap` → `_BaseMap` → `_MainTex` → `_BaseColor` keys (in that order — HDRP first, since DLC capitals use PBR), pick the largest-area texture.

### Pitfalls in the prefab walk

- **Unity is left-handed Y-up.** All transform composition stays in Unity's native space. The handedness flip (negate X on positions and normals; reverse triangle winding) happens once on final OBJ emission, mirroring `UnityPy/export/MeshExporter.py`. Doing the flip more than once is the most likely source of bugs.
- **Negative scale flips winding.** Detect via `det(M[:3,:3]) < 0` and emit triangle indices in original order to cancel the secondary flip from the X negation.
- **`m_Component` shape varies.** Newer Unity versions give `ComponentPair` objects with a `.component` PPtr; older versions give `(class_id, PPtr)` tuples. Handle both.
- **`ObjectReader` vs `PPtr` API.** ObjectReader exposes `parse_as_object()`; PPtr exposes `deref_parse_as_object()`. Calling the wrong one returns None silently and was the cause of one round-trip debugging session.
- **PBR texture keys.** Indus DLC capitals use HDRP-style materials with `_BaseColorMap`/`_BaseMap` instead of the legacy `_MainTex`/`_Diffuse`. Probe all four.

## Camera angle

The in-game world camera (`decompiled/Assembly-CSharp/GameCamera.cs`) is configured:

```cs
public Vector3 minZoomRotation = new Vector3(45f, 0f, 0f);
public Vector3 maxZoomRotation = new Vector3(45f, 0f, 0f);
public float minZoomFOV = 45f;
public float maxZoomFOV = 45f;
```

So the game tilts the camera 45° down with a 45° (telephoto) FOV. The camera also stays far away (`minZoomDistance = 30f, maxZoomDistance = 300f`) so individual buildings appear small in the frame.

Pinacotheca's render uses a 30° tilt with a wider 45° FOV, framing each building tightly. The shallower angle is a deliberate departure: at the game's 45° tilt with close framing, short-wide buildings (granary, barracks) appear nearly top-down because their height is small relative to their footprint. 30° gives a clearer 3/4 view in the cropped output.

There's also a separate `Portrait3DCamera.cs` for in-game unit/city portraits. It looks for a child `UnitOverrideCamera` GameObject on each prefab to pick a per-unit angle. Buildings don't have these overrides — only units do — so the main world camera setup is what governs how buildings appear.

## The "ground" inconsistency

After the prefab pipeline was working, an obvious inconsistency emerged in the output: some buildings (Library, Christian Temple, the composite prefabs) render with a visible plinth/ground, others (Granary, Watermill) appear to float in space.

The cause: **whether the building's artist baked a foundation slab into the mesh itself.**

Bottom-5%-of-vertical-extent footprint test:

| Mesh | Full XZ footprint | Bottom 5% footprint | Has built-in base? |
|---|---|---|---|
| `Library_LOD0` | 0.974 × 0.676 | 0.974 × 0.676 | Yes |
| `ChristianTemple_LOD0` | 10.18 × 12.55 | 10.18 × 12.55 | Yes |
| `Granary_LOD0` | 0.055 × 0.014 | 0.023 × 0.004 | No |
| `Watermill_LOD0` | 0.949 × 0.696 | ~0 × ~0 | No |

The composite prefabs (Maurya, Tamil, etc.) ship their own ground textures — `MauryaLow_Capital_BaseColor`, `Tamil_Capital_Pvt_BaseColor`, `AksumCapitol_Terrain_Diffuse` — so they always render with ground.

### Why we can't use the prefab's `Plane` meshes for ground

Each improvement prefab includes 3–7 `Plane` meshes positioned around the building. They look like obvious "ground tiles" but are unusable as direct color sources. **These are now filtered out** by `drop_splat_meshes()` in `prefab.py`, which matches on material name (`Splat*` prefix or exact `WaterNoFoam`) rather than mesh name — catching custom-named offenders like `Quad`, `MarketSplat`, `HamletFloor`, and `Maurya_PVT_Plane` that the older mesh-name-only filter missed.

| Mesh | Material | Texture |
|---|---|---|
| Granary Plane #0 | `SplatHeightDefault` | `Default_White` heightmap (16×16) |
| Granary Plane #13 | `SplatTextureDefaultPVT` | `KarnakPVT_Alpha` alphamap (2048×2048) |
| Library Plane #1 | `SplatHeightDefault` | `Default_White` heightmap |
| Watermill Plane #2-4 | `SplatTextureDefaultPVT` | `KarnakPVT_Alpha` alphamap |
| Watermill Plane #5 | `WaterNoFoam` | distortion + sky cubemap + foam |
| Watermill Plane #6-7 | `SplatHeightDefault` | `Default_White` heightmap |

These are inputs to Old World's terrain splat shader: heightmaps define elevation, alphamaps blend per-pixel weights between separate grass/dirt/stone color textures. There's no "diffuse" texture to render directly. Plugging them into a standard textured-mesh shader produces grayscale city-block-looking artifacts that double up with the 3D building (since the alphamap typically encodes a footprint of the building itself, painted onto the tile to support the game's far-zoom LOD popping).

In the game's actual view, two things hide this:

1. The custom terrain shader blends color textures so the alphamap is never visible directly.
2. The far camera distance with narrow FOV means the painted footprint is hidden behind the 3D building's silhouette.

Up close in our render, neither is true.

### Options considered for fixing the inconsistency

1. **Strip the built-in plinths** so every building is a floating portrait. Simple but loses the visual richness of the Library and Christian Temple bases.
2. **Synthesize a grass tile** beneath each building. The bundle has usable diffuse textures (`Grass_Tile_01_basecolor`, `Grass_Tile_02_Flowers_basecolor`, `Lush_Grass_02_Diffuse`) — pulling one in and rendering a quad before/after the building would work, but requires multi-texture rendering or a post-pass composite (~40 LOC).
3. **Reimplement the splat shader** to render the prefab's own Plane meshes correctly. Most faithful, most work.
4. **Leave as-is.** Inconsistent but each individual render is correct, and matches the asset author's intent.

**Currently implemented: option 1, with two paths to the cut height.** `strip_plinth_from_obj()` in `prefab.py` runs as a post-process on the baked OBJ before rendering.

**Path 1 (preferred): splat-plane Y as ground truth.** This is the same Y the game uses to deform terrain UP around the building — the prefab already encodes its ground line via the embedded `SplatHeightDefault` plane. `find_ground_y(parts)` reads the max world Y of the prefab's `SplatHeightDefault` plane (or fallback `SplatClutterDefault`/`SplatTextureDefaultPVT`); the extractor passes that to `strip_plinth_from_obj` as `cut_y_override`. About 25 of 56 single-piece improvements ship with splat planes — for those, splat-Y matches the building's actual floor within ±0.10 in 14 cases and is correct (vs. the heuristic over-cutting) in the disagreements. CITADEL, STRONGHOLD, AMPHITHEATER were all dramatically over-cut by the heuristic; splat-Y fixed them.

Two safety guards refuse a bad override and fall back to Path 2: (a) override exceeds `max_cut_fraction` (0.65) of the model's Y extent; (b) clamping the override would affect ≥50% of vertices. The latter catches edge-case authoring like WALL (whose entire mesh lies below Y=0) and BRICKWORKS (entirely above Y=2).

**Path 2 (fallback): bottom-5%-of-vertical-extent heuristic.** When no override is provided (no splat plane in the prefab; ~22 of 56 entries) or both safety guards refuse, the original heuristic runs: ≥80% XZ footprint coverage at the bottom 5% of Y = plinth; find slab top via vertex-density binning capped at `max_cut_fraction` extent; clamp sub-cut verts up to `cut_y` and drop faces whose three verts are all sub-cut. This is what handles religious buildings (cathedrals, monasteries, shrines) that ship without splat planes.

**Both paths share the clamp+drop emission.** Triangles straddling the cut are kept but their bottom verts are clamped to `cut_y`, flattening slab walls into a thin disc. The silhouette notch is invisible at hex-tile scale where downstream consumers composite the renders. Buildings without any plinth pattern sail through unchanged.

### How the game itself does it

The decompiled `TerrainTextureRenderer.cs:1591` (`RenderHeightSplats`) shows the in-game mechanism: an orthographic camera renders the `TerrainHeightSplat` layer (where every prefab's `SplatHeightDefault` plane lives) into a global heightmap that **deforms the terrain mesh UP around buildings**. The building's plinth bottom (Y ≈ -1 to -2 in prefab local space) ends up below the now-raised terrain mesh, hidden by Z-buffer. The game doesn't hide anything — it submerges the plinth.

Our isolated renders have no terrain to submerge into, so the ground stamp's Y becomes our cut line: anything below is what the in-game terrain would have hidden.

## Ground layer: capitals + urban tiles

Capital and urban-tile renders go through a layered path that adds a hex
ground tile + per-nation paint underneath the building geometry. The
single-piece improvements above stay on the original transparent-bg
path; only the 12 capitals + 10 urban tiles get the layered treatment.

Three layers, composited bottom-up by `src/pinacotheca/layered_render.py`:

1. **Biome base** — `TilePlains_01` (resolved from `TERRAIN_TEMPERATE` via
   the `terrain.xml → assetVariation.xml → asset.xml` chain). The prefab
   itself is a `TerrainTexturePVTSplat` plane with no MeshRenderer
   material; `Grass_Tile_01_basecolor × Hex_Mask` comes through the
   parsed splat fields and is pre-composed once in `biome_base.py`.
2. **Per-nation `TerrainTexturePVTSplat` planes** from the capital/urban
   prefab (Egyptian sand roads, Greek mosaic, Babylonian terraces, etc.),
   sorted ascending by `sortingOffset` so the in-game stacking order is
   preserved. `find_pvt_splats_in_prefab` (in `pvt_splats.py`) walks the
   prefab tree by script class — same pattern as `find_clutter_transforms_
   in_prefab` — and `compose_pvt_texture` produces an RGBA image as
   `albedo.rgb × tint.rgb` with alpha = `alpha[channel] × tint.a`,
   trusting mesh UVs (no per-tile texture replication).
3. **Existing combined building/clutter parts** on top.

All three layers share one orthographic camera (the renderer's existing
`force_upright=True` ortho path). To make this work, `render_mesh_to_image`
gained an opt-in `bbox_override` parameter: when provided, the camera is
framed around that combined bbox instead of the per-call OBJ. The
orchestrator computes the bbox once from the union of every layer's
baked OBJ vertices, then renders each layer with `autocrop=False` and the
shared bbox, alpha-composites them in PIL, and runs one final
`autocrop_with_padding` on the result. The renderer pipeline is otherwise
unchanged — same shader, same ortho frustum, same alpha-cutout.

Heightmap displacement (`TerrainHeightSplat`) is intentionally not
rendered. We still parse any height splats we encounter in the walker
as a side-effect drift check (the body-size assertion catches a future
game patch reordering fields), but discard the parsed result.

`MeshFilter` capitals (Maurya/Tamil/Yuezhi/Aksum/Hittite) ship their own
baked ground inside the prefab geometry; the layered ground composes
underneath, so their existing plinths still read correctly on top. Yuezhi
specifically walks to zero PVT planes; the orchestrator handles that case
by emitting biome + buildings only.

### Biome plane scaling

`TilePlains_01` is authored at ~18×18 game units — about 2× one in-game
hex (verified via `Tile.cs:1952`'s `getCornerTileOffset`, where the
corner-to-center distance is 5 units, giving an XZ bbox of ~8.66 × 10
per hex). The game relies on adjacent tiles' splats overlapping each
other for inter-tile blending; for our standalone icons we have no
neighbors, so the oversize hex would just leave a giant empty oval
around the rendered city.

`render_layered_ground` rescales the biome plane around origin to
match `union(buildings_xz_bbox, nation_pvt_xz_bbox)`. Uniform scale by
`max(target_x/biome_x, target_z/biome_z)`, floored at 0.2× to guard
against degenerate prefabs. The plane mesh's `Hex_Mask` alpha falloff
preserves the soft hex silhouette at the new footprint, so the icon
crops tightly around the buildings + nation paint instead of bleeding
past them.

## Lighting envelope

The fragment shader applies a directional shading factor with a
configurable floor:

```glsl
float ndotl = dot(N, light_dir);                         // [-1, 1]
float diffuse = mix(min_brightness, 1.0, ndotl*0.5+0.5); // [floor, 1]
```

Two callers, two values:

- **Buildings, units, improvements**: `min_brightness = 0.4`. 60% range
  on `diffuse`. Back-faces darken to ~0.4 of source albedo, lit faces
  hit 1.0. Restores face-by-face contrast that earlier iterations
  (0.7 floor) had washed out.
- **Ground layers** (biome quad + per-nation PVT planes,
  `flat_lighting=True`): `min_brightness = 1.0`. Skips directional
  shading entirely — these are flat horizontal Quads where the
  directional term would just dim every pixel by the same factor.

The 0.4 literal is the tuning knob; `renderer.py` near
`prog["min_brightness"].value`. See `docs/material-rendering.md` for
the full shader detail and the iteration history.

## Material rendering (normal mapping, occlusion, team color)

Beyond the diffuse texture, the renderer also samples (when available):

- **Normal maps** (`_BumpMap`, DXT5nm-encoded) for surface microgeometry
  — brick courses, panel breaks, decorative carvings. Per-vertex
  tangents flow through `bake_to_obj` as a custom `vtg x y z w` OBJ
  extension. The fragment shader builds a TBN matrix and perturbs the
  geometric normal.
- **Occlusion** from the packed
  `_MetalicRoughnessOcclusionTeamColor` texture's B channel. Applied
  with `occlusion_strength = 0.6` so concave joints read with depth
  without crushing brick walls. A B-mean threshold protects
  Library-style `_DetailTexture` materials with a different channel
  convention.
- **Neutral team color**: hand-painted pink placeholders in building
  diffuse textures (intended for runtime tinting via
  `_PrimaryTeamColor`) are swapped to neutral gray as a pre-process
  inside `find_diffuse_for_prefab`. Pink range:
  `R>200 ∧ 130<G<200 ∧ 130<B<200`, replaced with `(180, 180, 180)`.

These apply to every render that uses the buildings shader path — not
just the layered ground. See `docs/material-rendering.md` for the
shader source, channel layouts, the DXT5nm swizzle math, and tuning
knobs.

## Camera orientation: the 180° flip

The in-game world camera (`GameCamera.cs:54`, Euler `(45, 0, 0)`) sits south of its target and views the **-Z face** of buildings. By Unity convention an object's `transform.forward = +Z`, but Old World assets are authored with their **front facing -Z** so the in-game camera sees the entrance/decorated side.

Our renderer puts the OpenGL camera at OBJ +Z (`renderer.py:319`). Without compensation, every building shows its back. Flipping the camera to OBJ -Z would also mirror left/right (because the camera's local right vector reverses), which is the wrong fix.

The chosen fix is in `bake_to_obj`: an optional `pre_rotation_y_deg` (default 0° to keep the function reusable; the extractor passes 180°). It pre-multiplies a 4×4 Y rotation onto each part's world matrix. Y rotation is a proper rotation (`det = +1`) so the existing `flip_winding` logic for negative-scale parts is unaffected. Vertices and normals both flow through the same composed matrix, so the rotation applies uniformly.

No per-asset rotation overrides are needed. Earlier work added a `IMPROVEMENT_ROTATION_OVERRIDES` dict keyed on COURTHOUSE, but it turned out to be papering over a wrong-prefab bug — the curated list pointed at `Courthouse_low` (an unused mesh) instead of `Palace` (what the game actually uses for IMPROVEMENT_COURTHOUSE). The XML-driven discovery work (see `improvement-naming-alignment.md`) eliminated that bug class, and the override dict was deleted along with the curated lists.

There is also no longer a raw-mesh fallback path. The previous fallback existed because the curated list contained mesh names that weren't prefab GameObjects; with XML-driven discovery, every entry is a real prefab path, so `find_root_gameobject` + `walk_prefab` is the only render path.

## Asset discovery: XML-driven

The list of improvements to render is no longer hand-curated. `extract_improvement_meshes` calls `pinacotheca.asset_index.load_improvement_assets(xml_dir)`, which walks the game's `improvement.xml → assetVariation.xml → asset.xml` chain (plus DLC variants) to produce a list of `(zIconName, prefab_name)` pairs. Output filenames use `IMPROVEMENT_3D_{zIconName.removeprefix("IMPROVEMENT_")}.png` to match what downstream consumers (per-ankh) expect. See `docs/improvement-naming-alignment.md` for the full design.

A small `SUPPLEMENTAL_PREFABS` constant in `extractor.py` covers prefabs not represented in `improvement.xml` (currently only the four pyramid construction stages used by the build animation).

A small `PREFAB_DECODE_BLACKLIST` constant in `extractor.py` skips prefabs whose Texture2D decode causes UnityPy to SIGSEGV (currently only `Fort`). SIGSEGV bypasses Python `try/except`, so the only safe handling is to skip these before reading textures.

## File map

- `src/pinacotheca/asset_index.py` — XML chain parser. `load_improvement_assets(xml_dir)` returns one `ImprovementAsset` per unique `zIconName`. Pure-Python, no UnityPy dep. Reads `improvement.xml` + `improvement-event.xml`, `assetVariation.xml` + DLC variants, `asset.xml` + DLC variants.
- `src/pinacotheca/extractor.py` — `extract_improvement_meshes()` calls `load_improvement_assets()` then iterates `+ SUPPLEMENTAL_PREFABS`. Includes `PREFAB_DECODE_BLACKLIST` for SIGSEGV-causing prefabs. Also `build_texture_lookup()` (used by unit extraction) and `DIFFUSE_TEXTURE_SUFFIXES` constant.
- `src/pinacotheca/renderer.py` — `render_mesh_to_image()` with `force_upright` for buildings (Y-up, 30° tilt, ortho), `bbox_override` for shared-camera layered passes, `flat_lighting` for ground layers, plus optional `normal_map_image` and `packed_pbr_image` for tangent-space normal mapping and occlusion. See `docs/material-rendering.md` for the shader detail.
- `src/pinacotheca/prefab.py` — GameObject/Transform walker, world-matrix composer, OBJ baker (`bake_to_obj` with optional `pre_rotation_y_deg`, emits per-vertex `vtg` tangent lines when present), splat material constants and `find_ground_y` / `find_geometry_y_min` helpers, `strip_plinth_from_obj` with optional `cut_y_override`. Also the texture-search helpers (`find_diffuse_for_prefab`, `find_normal_map_for_prefab`, `find_packed_pbr_for_prefab`) and `apply_neutral_team_color`.
- `src/pinacotheca/biome_base.py` — resolves `TERRAIN_TEMPERATE` to `TilePlains_01` and pre-composes its hex-shaped grass diffuse for the layered ground bottom layer.
- `src/pinacotheca/pvt_splats.py` — hand-parser for `TerrainTexturePVTSplat` and `TerrainHeightSplat` MonoBehaviour bodies; prefab-tree walker; per-plane `albedo × alpha` compositor.
- `src/pinacotheca/layered_render.py` — multi-pass orchestrator for capitals + urban tiles. Composes biome + per-nation PVT planes + buildings under one shared camera; rescales the biome plane to fit the buildings/PVT footprint.
- `tests/test_asset_index.py` — synthetic-XML tests for the chain (SingleAsset, aiRandomAssets, DLC merge, dedupe-by-zIconName, broken-chain skipping).
- `tests/test_prefab.py` — synthetic unit tests for the prefab math (quaternion → matrix, TRS chain, normal transform under non-uniform scale, X-flip-once, winding flip on negative scale, splat-Y helpers, `cut_y_override` safety guards, `pre_rotation_y_deg` Z-flip).
- `scripts/probes/` — exploration scripts used during the investigation (mesh enumerator, texture finder, prefab inspector). Not required at runtime.

## Reference: game source files

These are decompiled C# files from `decompiled/Assembly-CSharp/` in the Old World install directory, useful for figuring out the in-game rendering setup:

- `GameCamera.cs` — main world camera; pitch/FOV/zoom configuration
- `Portrait3DCamera.cs` — unit/city portrait renderer; uses per-prefab `UnitOverrideCamera` child GameObjects
- `MapCamera.cs` — minimap/overview camera (not the main view)

For UnityPy internals:

- `UnityPy/export/MeshExporter.py` — does the X-flip on positions and normals when writing OBJ
- `UnityPy/export/MeshRendererExporter.py` — canonical pattern for walking GameObject components and resolving Material → Texture
- `UnityPy/classes/PPtr.py` — `deref()`, `deref_parse_as_object()`, `bool(pptr)` for null check
- `UnityPy/files/ObjectReader.py` — `peek_name()` for cheap name scans without full parsing; `parse_as_object()` for the parsed dataclass
