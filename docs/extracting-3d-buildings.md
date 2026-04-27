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

Each improvement prefab includes 3–7 `Plane` meshes positioned around the building. They look like obvious "ground tiles" but are unusable as direct color sources:

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

We chose option 4 for now. Option 2 is the most likely follow-up.

## File map

- `src/pinacotheca/extractor.py` — `IMPROVEMENT_MESHES` curated list (~50 entries), `extract_improvement_meshes()`, `COMPOSITE_PREFABS` list, `extract_composite_meshes()`. Also `build_texture_lookup()` and `DIFFUSE_TEXTURE_SUFFIXES` constant for cross-format texture matching (`_diffuse`, `_albedo`, `_diff`, `_basecolor`, `_basemap`, `_maintex`).
- `src/pinacotheca/renderer.py` — `render_mesh_to_image()` with `force_upright` parameter for buildings (always Y-up, 30° tilt, 45° FOV).
- `src/pinacotheca/prefab.py` — GameObject/Transform walker, world-matrix composer, OBJ baker.
- `tests/test_prefab.py` — synthetic unit tests for the prefab math (quaternion → matrix, TRS chain, normal transform under non-uniform scale, X-flip-once, winding flip on negative scale).
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
