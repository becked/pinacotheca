# Runtime-Composed Nation Capitals

## Status: implemented

The 7 sparse capitals + every per-nation urban tile + Farm/Mine/Pasture/Camp/Grove + a couple of generic clutter prefabs (CITY_SITE, OUTPOST_RUINS) now render via `src/pinacotheca/clutter_transforms.py` as standard `IMPROVEMENT_3D_*.png` outputs. PVT splats remain unrendered (deferred — a separate follow-up if anyone wants the per-nation terrain dirt under the cities).

What got built:

- **`src/pinacotheca/clutter_transforms.py`** — hand-parser for the `ClutterTransforms` MonoBehaviour binary against the field layout below, plus the prefab-tree walker that locates `ClutterTransforms` by script class (handles Egypt's nested same-name child), expands each `(model, instance)` pair into a `PrefabPart` with world matrix `parent_world @ instance.TRS`, and feeds the existing `bake_to_obj` + `render_mesh_to_image` pipeline. Promotes `PPtr`/`Reader`/`ObjectReaderAsPPtr`/`script_class`/`find_object_by_path_id` from the probes.
- **`src/pinacotheca/asset_index.py`** — added `load_urban_assets` walking `asset.xml` for `ASSET_<NATION>_URBAN` entries (no AssetVariation wrapper).
- **`src/pinacotheca/extractor.py`** — augments `walk_prefab`'s output with clutter-expanded parts before the bake step. Adds `globalgamemanagers.assets` to the env (needed for `m_Script` PPtr resolution). Adds urban tiles to the jobs list. Logs `[CT]` lines per prefab so each run surfaces which prefabs carry clutter.
- **`src/pinacotheca/prefab.py`** — `drop_splat_meshes` now also drops materialless parts (capitals' `*Bull` no-op `TerrainHeightSplat` placeholders), and the over-defensive "if all dropped, restore originals" fallback was removed: with clutter augmentation in place, "all `MeshFilter` parts are splat/materialless" is a legitimate signal that the real geometry comes from the clutter expansion.

What surprised the investigation:

- **FARM/MINE/PASTURE/CAMP/GROVE all have `ClutterTransforms`** — the scope table called them "PVT only" but the survey log proved them clutter-driven. They render automatically through the augmentation, no extra wiring needed. Same for `CITY_SITE` and `OUTPOST_RUINS`.
- **Egypt's prefab walks to zero `MeshFilter` parts after the splat/materialless filter** — the Obelisk geometry is reachable through the prefab tree but the existing splat filter would have dropped it under the old fallback. With the fallback removed it's still in the clutter expansion (`Obelisk` is one of the 119 clutter models, not a separate `MeshFilter` leaf as the doc previously claimed).
- **`load_urban_assets` discovered 11 urban tiles** including `INDIA_URBAN`, `AKSUM_URBAN`, `HITTITE_URBAN` (the latter two have the DLC/base-game capitals as full `MeshFilter` trees but their *urban* tile is clutter-driven).

The renderer needed no changes. The original "renderer needs no changes" claim from the investigation held up: every clutter mesh runs through the same `bake_to_obj` + `render_mesh_to_image` pipeline that handles improvements and DLC capitals.

## The problem (reframed)

Old World has 12 nation capitals. Five render correctly via our normal prefab pipeline:

| Nation | Source | Why it works |
|---|---|---|
| Maurya | EOTI DLC | Full city geometry baked into one prefab as a `MeshFilter` tree |
| Tamil | EOTI DLC | Full city geometry baked into one prefab as a `MeshFilter` tree |
| Yuezhi | EOTI DLC | Full city geometry baked into one prefab as a `MeshFilter` tree |
| Aksum | base game | Full city geometry baked into one prefab as a `MeshFilter` tree |
| Hittite | base game | Full city geometry baked into one prefab as a `MeshFilter` tree |

Seven (Greece, Persia, Rome, Carthage, Babylonia, Assyria, Egypt) initially appear empty — their prefab tree has no `MeshFilter` leaves with real building geometry. Just splat planes (PVT albedo + height), a no-op "Bull" placeholder, and per-prefab specials (Egypt's obelisk, Carthage/Babylon LakeWater).

**The original investigation took the wrong fork.** It assumed the missing visual identity lived in the PVT splat textures (Stage 1-4 below) and proposed a partial re-implementation of the terrain shader to reconstruct it. After investigating, that turned out to be wrong: PVT splats only paint *dirt patches* under the cities. We confirmed this by compositing `albedo × alpha` for Egypt and getting "grass with sand patches where roads and buildings used to be" — nothing Egyptian, no buildings, no architectural identity.

**The actual building geometry lives in a separate MonoBehaviour: `ClutterTransforms`.** Each sparse-capital prefab carries an 11-17KB `ClutterTransforms` instance referencing 80-125 unique building/tree/structure meshes plus a list of placement transforms (position/rotation/scale per instance). Greek capital = 90 meshes (`bigHome.NNN`, `Cypress.NNN`, `Gazeebo.NNN`, ...). Roman capital = 85 meshes including `TheaterPompey` literally by name. Each mesh has been verified to render through the existing pipeline with no modifications (`scripts/probes/render_clutter_mesh.py`).

The renderer challenge for the 7 sparse capitals is therefore: **walk `ClutterTransforms`, instantiate each mesh at each transform, composite into a single render** — same machinery as our existing improvement pipeline, just with a binary parser for the nested `List<Model>` structure.

The PVT splat layer is a useful *secondary* visual (the Greek mosaic dirt under the columns), but it is not where the cities live, and shipping the project does not require rendering it.

## Where the city geometry lives: ClutterTransforms

Verified via `scripts/probes/scan_clutter_meshes.py` — each sparse-capital prefab carries one `ClutterTransforms` MonoBehaviour (the GameObject that previously appeared as `GeeceCapitalTrans` / `rome-Capital` / `Egypt_Capital`-as-child and was misclassified as "the 12KB MonoBehaviour of unknown purpose").

The class definition (`decompiled/Assembly-CSharp/ClutterTransforms.cs:155-206`):

```csharp
public class ClutterTransforms : ClutterBase {
    public List<Model> models;
    public TerrainClutterType clutterType = TerrainClutterType.MinorBuildings;  // ← default category
    // ... TilingProperties, options, etc.

    [Serializable]
    public class Model {
        public Mesh mesh;                          // ← the actual 3D building/tree mesh
        public Material material;
        public ClutterTransform meshTransform;
        public List<ClutterTransform> transforms;  // ← every placement (pos/rot/scale)
        // ...
    }
}

[Serializable]
public class ClutterTransform {
    public bool initialized;
    public Vector3 position;
    public Vector3 rotation;  // euler angles
    public Vector3 scale;
    // 4 + 12 + 12 + 12 = 40 bytes per instance
}
```

`ClutterTransforms.Regenerate()` iterates `models`, takes each `model.mesh` + `model.material`, and instances it at each `model.transforms[i].Matrix` via `Graphics.DrawMesh`. Static-batched if `useStaticBatching=true`. **This is exactly the operation our existing renderer performs** for improvement meshes — just driven by a list of instance matrices instead of a transform tree.

### Verified mesh inventory per capital (from PPtr scan)

| Capital | ClutterTransforms size | # unique meshes | Sample names |
|---|---|---|---|
| Greek | 12,532 B | 90 | `bigHome.001..034`, `Cube.003..027`, `Cypress.001..020`, `Gazeebo.001..020`, `PalmTree.002..007`, `TentA3/B2.001..006` |
| Roman | 11,716 B | 85 | `4door.001..009`, `BigTower`, `Cube.001..008`, `Cylinder.001`, `Cypress.001..020`, `Mansion.001..002`, `Rome-buildings01..42`, `RoundHome.001..002`, `roundvilla.001`, `SlantTower`, `SmallHome.001..002`, `SmallTower.001`, `TallHome.001..003`, `Tent.001..004`, **`TheaterPompey`**, `Villa.001..002`, `WideMansion.001..004` |
| Egyptian | 16,340 B | 118 | `BackGate`, `bigHome.001..030+`, plus more |
| Persian | 17,156 B | 125 | (largest of the seven) |
| Babylonian | 12,940 B | 94 | includes `babylonStatuelow.001..002` |
| Carthaginian | 14,436 B | 105 | |
| Assyrian | 11,132 B | 81 | (smallest) |

Every nation has cypress trees, palm trees, tents, gazebos, multi-story homes — a complete architectural roster. Materials are simple: 1-2 shared materials per capital (`GreeceMat`, `RomeTrim`, `Carthage`-something, etc.) applied to all the meshes of that nation.

### Renderer sanity check passed

`scripts/probes/render_clutter_mesh.py` loaded 7 sample meshes (Greek `bigHome.001`/`Cypress.001`/`Gazeebo.001`, Roman `TheaterPompey`/`Mansion`/`BigTower`, Egyptian `BackGate`) by pathID, wrapped each as a single `PrefabPart` with identity transform, and ran them through the existing `bake_to_obj` + `render_mesh_to_image` pipeline with the nation's material's diffuse texture. **All 7 rendered as recognizable 3D building/tree PNGs** with no renderer changes — output in `scripts/probes/output/clutter_renders/`.

This means the renderer pipeline already supports these meshes. The unbuilt work is:

1. A binary parser for `ClutterTransforms` that extracts `[(mesh_pptr, material_pptr, [(position, rotation_euler, scale), ...])]`
2. A composite render that instances each mesh at each transform — either by emitting one big OBJ with all instances baked into world coords (reuses our existing single-render call), or by chaining N draws into one moderngl context
3. Discovery via the XML chain (capitals are already discovered by `load_capital_assets`)

## Scope and side-effect targets

| Asset class | Approach | We render today? | Work to add |
|---|---|---|---|
| Improvements (Library, Temple, Bath…) | Baked `MeshFilter` tree | Yes — XML chain | — |
| Capitals: 4 DLC + Aksum + Hittite | Baked `MeshFilter` tree | Yes | — |
| Capitals: 6 sparse base game | `ClutterTransforms` MonoBehaviour | **No** — needs binary parser | This doc |
| Urban tiles: every nation | `TerrainTexturePVTSplat` (terrain only, no buildings) | No | Optional terrain-tile renderer |
| Improvements: Farm, Mine, Pasture | `TerrainTexturePVTSplat` (terrain only) | No | Optional, low-priority |
| Improvements: Grove, Camp, Windmill | PVT + clutter splat | No | Needs `TerrainClutterSplat` support |

**The capital work doesn't unlock urban tiles or PVT-only improvements** — those are on a separate code path (terrain texture composition, no per-prefab mesh inventory). Building the ClutterTransforms parser unlocks ONLY the 7 sparse capitals (which is the high-value target). PVT terrain rendering for urban tiles + Farm/Mine/Pasture is a separate, optional follow-up.

## PVT splat investigation (background)

> **Skip ahead to [Implementation plan](#implementation-plan) if you don't need the PVT details.** Everything from here through "Hand-parsing requirement" documents the terrain-layer investigation that *led* to the ClutterTransforms answer. The PVT layer is real and renderable but is not where the building geometry lives — it paints dirt under the cities. Kept for reference and to preserve verified findings (texture formats, field layouts, etc.) in case the PVT layer ships as an optional secondary visual.

The investigation started by assuming PVT splats were the missing piece. They turned out not to be, but the work produced verified ground truth about how the terrain layer is composed. Composite preview (`scripts/probes/composite_pvt.py`) on Egypt shows grass with sand patches; nothing Egyptian.

### How the game composes the PVT terrain layer

Four stages, all in `decompiled/Assembly-CSharp/`:

#### Stage 1 — authoring time (per-nation prefab properties)

Each Capital prefab contains GameObjects (named like `GreeceCapitalPVT`, `Egypt_height`) with `TerrainTexturePVTSplat` or `TerrainHeightSplat` MonoBehaviour components attached. The PVT component holds per-nation properties (`TerrainTexturePVTSplat.cs:48-99`):

```csharp
public Texture albedoMap;        // e.g., GreeceCapTerrain
public Texture normalMap;        // mostly null — only Rome sets one
public Texture metallicMap;      // never used by capitals
public Texture roughnessMap;     // never used by capitals
public Texture alphaMap;         // e.g., GreeceCapTerrain_M (R-channel sampled as mask)
public Color   albedoTint;       // (1,1,1,1) universally
public float   normalMapIntensity;
public float   metallic, roughness;
public bool    materialUseWorldUVs;
public float   materialTiling;   // 1.0 universally
public int     atlasIndex;       // alternative: pre-packed atlas mode (unused)
```

Each splat plane sits on the special Unity layer `TerrainTexturePVTSplat` (`TerrainTexturePVTSplat.cs:133`). Heightmap-bearing planes use `TerrainHeightSplat` layer (`TerrainHeightSplat.cs:10`). These layers are invisible to the main player camera.

#### Stage 2 — runtime spawn (CityRenderer)

When a city is built, `CityRenderer.cs:90-93` does the standard:

```csharp
AssetVariationType assetVariationType = (cachedIsCapital
    ? infoNation.meCapitalAsset
    : infoNation.meCityAsset);
cityObject = gApp.RenderManager.SpawnAsset(assetVariationType, ...);
```

Just `Object.Instantiate`. The splat planes are now in the scene at their authored positions but invisible to the main camera (because of layers). Plus city projects (Walls, Towers, Moat — `CityRenderer.cs:94-101`) get spawned as separate sub-objects when the player builds them.

#### Stage 3 — per-cell baking (the magic)

`TerrainTextureRenderer.cs:1690` (`RenderCellSplats`) runs whenever a terrain cell is dirty. For each affected cell:

```csharp
// Position an orthographic camera looking straight down at the cell
Camera textureSplatPVTCamera = terrainSetup.textureSplatPVTCamera;
transform2.localPosition = new Vector3(bounds.center.x, ..., bounds.center.z);
textureSplatPVTCamera.orthographicSize = z / 2f;
textureSplatPVTCamera.aspect = x / z;

// First pass: render the albedo (painted color) layer
textureSplatPVTCamera.targetTexture = cellRenderTextureAlbedo[detailLayer];
textureSplatPVTCamera.Render();

// Second pass: render normals (toggle via shader keyword)
GlobalKeyword keyword = GlobalKeyword.Create("_TerrainPVTRenderNormal");
Shader.EnableKeyword(in keyword);
textureSplatPVTCamera.targetTexture = cellRenderTextureNormal[detailLayer];
textureSplatPVTCamera.Render();

// Composite into the cell's permanent textures
Graphics.CopyTexture(cellRenderTextureAlbedo[detailLayer], 0, textureSet.albedo, 0);
```

The orthographic camera only sees the splat planes (because they're on the `TerrainTexturePVTSplat` layer). Each splat plane's custom shader samples its `albedoMap`, `normalMap`, etc., multiplied by the `alphaMap` mask. The camera output is a per-cell texture containing all splat contributions baked together.

A separate camera (`heightSplatCamera`, `RenderCellSplats:1702-1712`) does the same for the `TerrainHeightSplat` layer — that becomes the terrain *deformation* heightmap.

A `_TerrainPVTRenderNormal` shader keyword toggles whether the splat shader emits albedo or normals on a given pass — same camera, two render passes.

#### Stage 4 — terrain mesh shading

The actual hex-tile terrain mesh has a shader that:
1. Samples `cellRenderTextureAlbedo` for color (now containing baked nation paint)
2. Samples `cellRenderTextureNormal` for surface direction
3. Samples `cellRenderTextureHeight` for vertex displacement (so painted "mountains" become actual height)
4. Blends with biome base textures (grass / sand / stone / snow underneath)
5. Applies PBR lighting

Result: ground beneath a Greek city has Greek mosaic patterns visible from any view angle, with proper shading and lighting, blended onto whatever biome (grassland, hills, coast) the city happens to sit on.

### Texture inventory per nation (PVT splat layer)

**Verified ground truth** from `scripts/probes/parse_pvt_splat_binary.py` — a hand-parsed binary reader against the field layout from `TerrainTexturePVTSplat.cs`. These are the actual `albedoMap`/`heightmap`/`alphaMap`/etc. PPtrs each splat plane resolves to.

| Capital | Splat plane | Albedo | Alpha | Normal | Heightmap | Height intensity |
|---|---|---|---|---|---|---|
| Greece | GreeceCapitalPVT | `GreeceCapTerrain` | `GreeceCapTerrain_M` | (none) | — | — |
| Greece | GreeceCapitalHeight | — | — | — | `GreeceCapTerrain_H` | 0.7 |
| Greece | GreeceCapitalBull | — | — | — | `GreeceCapFlatTerrain` | **0.0 (no-op)** |
| Rome | RomePVT | `romcapitalSplat` | `romcapital_CLUT` | `RomeGroundNormal` (×0.30) | — | — |
| Rome | RomeHeightPVT | — | — | — | `RomeGroundHeight` | 4.9 |
| Rome | RomeCapBull | — | — | — | `GreeceCapFlatTerrain` | **0.0 (no-op)** |
| Egypt | EgyptPVT | `landEgypt_roads` | `landEgypt_Mask` | (none) | — | — |
| Egypt | Egypt_height | — | — | — | `landEgypt_height` | -0.2 |
| Egypt | EgyptCapBull | — | — | — | `GreeceCapFlatTerrain` | **0.0 (no-op)** |
| Persia | Persia_CapitalPVT | `persiaCapPVT` | `persia_capMask` | (none) | — | — |
| Persia | Persia_CapitalBull | — | — | — | `GreeceCapFlatTerrain` | **0.0 (no-op)** |
| Babylon | babylon_PVT | `landBabylon` | `landBabylon_m` | (none) | — | — |
| Babylon | Babylon_height | — | — | — | `lakeBabylon` | -0.2 |
| Babylon | BabylonCapBull | — | — | — | `GreeceCapFlatTerrain` | **0.0 (no-op)** |
| Carthage | CarthageMoundPVT | `Carthagepvt` | `Carthagepvt_mask` | (none) | — | — |
| Carthage | CarthageMoundHeight | — | — | — | `CarthageMoundMask` | 0.5 |
| Carthage | CarthagwCapBull | — | — | — | `GreeceCapFlatTerrain` | **0.0 (no-op)** |
| Assyria | AssyriaCapPVT | `AssyriaCapTerrain` | `AssyriaCapmask` | (none) | — | — |
| Assyria | AssyriaCapHeight | — | — | — | `AssyriaCapH` | -0.5 |
| Assyria | AssyriaCapBull | — | — | — | `GreeceCapFlatTerrain` | **0.0 (no-op)** |

Universal across all 7 capitals (verified):

- **`alphaMapChannel = 0`** (sample R channel)
- **`albedoTint = (1,1,1,1)`** (no color modulation)
- **`materialTiling = 1.0`**
- **`packInAtlas = false`** (atlas mode unused)
- **`normalMapIntensity = 1.0`** except Rome which uses 0.30
- All PVT planes use shared material `SplatTextureDefaultPVT` (pathID 391); all height planes use `SplatHeightDefault` (pathID 387)
- **No capital uses `metallicMap`, `roughnessMap`, or any atlas texture.** Most don't use `normalMap` either — only Rome does.

Verified findings that flip earlier assumptions:

- **Babylon DOES have per-nation textures.** They're prefixed `landBabylon` / `lakeBabylon`, which my earlier name-prefix probe missed. Babylon's `babylon_PVT` references `landBabylon` (albedo) and `landBabylon_m` (alpha); `Babylon_height` uses `lakeBabylon` as a heightmap (likely shapes the hanging-gardens terraces). Babylon is renderable.
- **Egypt's `landEgypt_*` convention is correct** (the original doc was right; my regex-based texture inventory missed these). EgyptPVT references `landEgypt_roads` + `landEgypt_Mask`; Egypt_height uses `landEgypt_height`.
- **Rome uses lowercase `rom*` textures** (`romcapitalSplat`, `romcapital_CLUT`) — also missed by case-sensitive prefix matching. Rome is the only capital using a normalMap (`RomeGroundNormal`).
- **Greece's `greece_NRM` is NOT referenced** by the splat MonoBehaviour. The doc previously assumed it was. The actual GreeceCapitalPVT has `normalMap = null`. Either the artist authored a NRM but forgot to wire it, or the visual design relies on albedo only.
- **The "Bull" GameObjects are universally a no-op.** All 7 capitals have a `*CapBull` (or `*CapitalBull`) GO that references the same shared placeholder `GreeceCapFlatTerrain` heightmap with `intensity = 0.0`. They contribute nothing visually. **Renderer should skip them.**
- **Heightmap intensities vary wildly and include negatives:** Greece +0.7, Rome **+4.9** (huge — explains why Rome reads as dramatic), Egypt -0.2, Carthage +0.5, Assyria -0.5, Babylon -0.2. Negatives carve depressions (Egypt's irrigation, Babylon's lake basin, Assyria's moat).
- **Compositing order is given by `sortingOffset`** (a TerrainSplatBase field): Bull=60, PVT=120-129, Height=163-201. Lower renders first. This is explicit z-order — use it, not transform/walk order.
- **Multiple texture-naming conventions per nation.** `Greece*`/`greece*`, `Carthage*`/`carthage*`, `Rome*`/`rom*`/`romcapital*`, `Egypt*`/`landEgypt*`, `Babylon*`/`landBabylon*`/`lakeBabylon*`, `Persia*`/`persia*`. Cannot rely on name-prefix discovery — must read the splat MonoBehaviour to know which texture is referenced.
- **Carthage + Babylon LakeWater** planes (cothon, lake) exist as separate GameObjects to filter.
- File sizes vary (512² – 2048²); renderer must handle arbitrary input sizes.

#### Mesh GameObjects per capital prefab (verified via probe)

The doc previously characterized these prefabs as just "splat planes." The actual structure has more pieces:

| Prefab | Mesh-bearing GameObjects (material) | Notes |
|---|---|---|
| Greece_Capital | GreeceCapitalHeight, GreeceCapitalPVT (`SplatTextureDefaultPVT`), **GreeceCapitalBull** (no material on MeshRenderer), GeeceCapitalTrans (`ClutterTransforms`, 12.5KB ≈ 310 clutter prop instances) | "Bull" is uncatalogued; clutter rendered separately |
| Rome_Capital | RomePVT (`SplatTextureDefaultPVT`), RomeHeightPVT (`SplatHeightDefault`), RomeClutterPVT (`SplatClutterDefault`), **RomeCapBull** (`SplatHeightDefault`) | clutter splat present |
| Egypt_Capital | EgyptPVT, Egypt_height, **EgyptCapBull** (`SplatHeightDefault`), WaterPool (`LakeWater`), Obelisk (`Obelisk`) — plus a nested duplicate `Egypt_Capital` GO | Obelisk is real geometry; nested same-name child is suspicious |
| Persia_Capital | Persia_CapitalPVT, **Persia_CapitalBull** | Persia has Bull too |

The "**Bull**" GameObjects appear in *every* capital. **Verified via binary parse**: every Bull is a `TerrainHeightSplat` referencing the shared `GreeceCapFlatTerrain` placeholder heightmap with `intensity = 0.0` — a no-op. They contribute nothing visually and the renderer should skip them.

### Why early PVT screenshots looked unimpressive

The raw `GreeceCapTerrain` texture viewed straight-on is just the *input*. It's missing:
1. **Multiplied by the alphamap** — `GreeceCapTerrain_M.R` masks the painted region; without it the albedo extends edge-to-edge as a flat poster
2. **Heightmap as vertex displacement** — `GreeceCapTerrain_H` at intensity 0.7 gives the painted "mountains" actual geometric height (Rome at intensity 4.9 is the dramatic case)
3. **Blended with biome base** — surrounding grass/dirt would feather into the city paint at the edges
4. **Proper directional lighting on the displaced surface** — sun at the right angle gives the height bumps real shading, even without a normal map (most capitals don't use one)

A 30° perspective tilt alone (which we tested) doesn't help — it just makes the flat poster look like a tilted poster. And even with displacement + lighting, the result reads as "Greek-flavored ground" not "Greek city" — because the buildings are not in PVT, they're in `ClutterTransforms`.

### PVT hand-parsing requirement (resolved investigation)

Verified via `scripts/probes/dump_greece_components.py`: `TerrainTexturePVTSplat` (and every other custom MonoBehaviour in these prefabs) has **no embedded TypeTree** in `resources.assets`. Concretely:

- `reader.read_typetree()` raises `ValueError`
- `reader.parse_as_object()` reads only the 32-byte base MonoBehaviour header (m_GameObject, m_Enabled, m_Script, m_Name) and fails on the script-specific tail with `"Expected to read N bytes, but only read 32 bytes"`
- The script class itself can be resolved (via the m_Script PPtr → MonoScript → m_ClassName), but the field values cannot

**Mitigation: hand-parse the binary against the C# field layout. Verified working** (`scripts/probes/parse_pvt_splat_binary.py`). The PVT field layouts compose as:

| Class | Layout | Body size |
|---|---|---|
| `MonoBehaviour` header | m_GameObject(12) + m_Enabled aligned(4) + m_Script(12) + m_Name length-0(4) | 32 |
| `TerrainSplatBase` (base) | int sortingOffset | +4 |
| `TerrainTexturePVTSplat` derived | bool packInAtlas(4) + 3×Texture atlases(36) + bool useSimpleMode(4) + Material(12) + bool useWorldUVs(4) + float tiling(4) + 5×Texture maps(60) + int alphaMapChannel(4) + Color albedoTint(16) + 3×float(12) + int atlasIndex(4) + Vector4 textureArrayIndices(16) | +176 |
| **Total** | | **212** |
| `TerrainHeightSplat` derived | bool useSimpleMode(4) + Material(12) + bool overrideWorldUV(4) + 3×float(12) + Vector2 alphamapScaleBias(8) + 2×Texture(24) | +64 |
| **Total** | | **100** |

Body sizes match observed MonoBehaviour byte counts exactly. PPtr binary form: `int32 m_FileID + int64 m_PathID = 12 bytes`, little-endian. Bool serializes as 1 byte then aligns to 4. Script class names are resolved via the `m_Script` PPtr — most have `m_FileID=1` (external `globalgamemanagers.assets`), so that file must be loaded into the UnityPy environment alongside `resources.assets`.

The same approach generalizes to `ClutterTransforms`, but with nested variable-length Lists. See the [Implementation plan](#implementation-plan) for the equivalent `ClutterTransforms` field layout.

## Implementation reference (now built — kept for layout reference)

The sections below were the pre-implementation plan. The parser, expander, and wiring are now in `src/pinacotheca/clutter_transforms.py`; see that module's docstrings for the canonical reference. The field-layout table here is still the source of truth for the binary parser.

### Phase 1: hand-parse `ClutterTransforms`

A new `src/pinacotheca/clutter_transforms.py` module that:

1. Walks the prefab tree.
2. Finds the GameObject hosting a MonoBehaviour whose script class resolves to `ClutterTransforms`. **Find by class, not by name** — names vary (`GeeceCapitalTrans`, `rome-Capital`, nested `Egypt_Capital` child). The `script_class()` helper in `scripts/probes/parse_pvt_splat_binary.py` reads the MonoBehaviour's `m_Script` PPtr and resolves the `m_ClassName`. Egypt's `ClutterTransforms` lives on a *child* GameObject also named `Egypt_Capital`; the walker must descend into the prefab tree, not just check the root.
3. Hand-parses the MonoBehaviour binary against the field layout below (the layout was derived from `decompiled/Assembly-CSharp/ClutterTransforms.cs` and verified by byte arithmetic against the observed body sizes in all 7 sparse capitals).

Module-level types to define (or promote from `parse_pvt_splat_binary.py`):

```python
@dataclass(frozen=True)
class PPtr:
    file_id: int      # int32 m_FileID
    path_id: int      # int64 m_PathID

    def is_null(self) -> bool:
        return self.file_id == 0 and self.path_id == 0

@dataclass(frozen=True)
class ClutterInstance:
    position: tuple[float, float, float]
    rotation_euler: tuple[float, float, float]  # euler angles in degrees
    scale: tuple[float, float, float]

@dataclass(frozen=True)
class ClutterModel:
    mesh: PPtr
    material: PPtr
    mesh_transform: ClutterInstance     # 40 bytes (initialized + 3 Vector3s)
    atlas_index: int
    instances: list[ClutterInstance]    # variable-length List<>
    ignore_heightmap: bool
    use_procedural_damage: bool
    clutter_override: int
    lod_quality_level: int
    show: bool

@dataclass(frozen=True)
class ParsedClutterTransforms:
    fade_out_when_occupied: bool
    use_static_batching: bool
    use_indirect_instancing: bool
    use_heightmap: bool
    use_world_tiling: bool
    # TilingProperties fields (76 bytes, all serialized even when useWorldTiling=False)
    tiling_non_uniform_size: bool
    tiling_zone_size: float
    tiling_zone_size_2d: tuple[float, float]
    tiling_mask: PPtr
    tiling_mask_breakpoint: float
    tiling_non_uniform_mask_scale: bool
    tiling_mask_size: float
    tiling_mask_size_2d: tuple[float, float]
    tiling_mask_channel: int
    tiling_apply_mask_in_editor: bool
    tiling_preview_mask: bool
    tiling_hide_tiled_copies_in_editor: bool
    tiling_use_world_position_for_offset_in_editor: bool
    tiling_offset_in_editor: tuple[float, float]
    # End TilingProperties.
    override_material: PPtr
    clutter_type: int
    models: list[ClutterModel]
    gizmo_radius: float
    selected_index: int
```

Note: `ClutterBase` (the parent class of `ClutterTransforms`) contributes **zero serialized bytes** — verified from `decompiled/Assembly-CSharp/ClutterBase.cs:1-20`: only `protected List<InstanceRenderData>` (runtime cache, not serialized) and a `private bool localEnabled` (private, not serialized). So the script-specific body starts immediately after the 32-byte MonoBehaviour header with `bool fadeOutWhenOccupied`. (No `sortingOffset` here, despite the PVT pattern's similar-looking base class.)

Field layout (from `ClutterTransforms.cs:208-244` and `ClutterTransform.cs:5-15`):

| Section | Layout | Bytes |
|---|---|---|
| MonoBehaviour header | as before | 32 |
| ClutterBase | (no `[SerializeField]` fields — verified) | 0 |
| ClutterTransforms scalars | bool fadeOutWhenOccupied(4) + bool useStaticBatching(4) + bool useIndirectInstancing(4) + bool useHeightmap(4) + bool useWorldTiling(4) | 20 |
| TilingProperties | bool nonUniformSize(4) + float tilingZoneSize(4) + Vector2 tilingZoneSize2D(8) + Texture2D mask(12) + float maskBreakpoint(4) + bool nonUniformMaskScale(4) + float maskSize(4) + Vector2 maskSize2D(8) + int maskChannel(4) + bool applyMaskInEditor(4) + bool previewMask(4) + bool hideTiledCopiesInEditor(4) + bool useWorldPositionForOffsetInEditor(4) + Vector2 tilingOffsetInEditor(8) | 76 |
| Material overrideMaterial | PPtr | 12 |
| TerrainClutterType clutterType | int enum | 4 |
| List<Model> models | int count + N × Model | variable |
| Model | bool initialized(4) + Mesh PPtr(12) + Material PPtr(12) + ClutterTransform meshTransform (4 + 12 + 12 + 12 = 40) + int atlasIndex(4) + List<ClutterTransform> transforms (4 + N×40) + bool ignoreHeightmap(4) + bool useProceduralDamage(4) + int clutterOverride(4) + int lodQualityLevel(4) + bool show(4) | 96 + N×40 |
| float gizmoRadius | float | 4 |
| int selectedIndex | int | 4 |

Quick byte-count check on Greece's 12,532-byte body: `32 + 20 + 76 + 12 + 4 + 4_count + 4 + 4 + (N_models × (96 + N_inst×40)) ≈ 12,500`. With ~5 models × ~60 instances each ≈ 5×(96 + 60×40) = 5×2496 = 12,480 ✓ within rounding.

Working prototype: `scripts/probes/scan_clutter_meshes.py` (PPtr scan, no list parse). The full structured parser still needs to be written.

### Phase 2: composite multi-instance render

The natural call shape is: pass a list of `(mesh, world_matrix, material)` tuples to one render. Two ways to wire it:

**Option A — emit one combined OBJ.** Use existing `bake_to_obj` semantics: extend it to accept a list of `PrefabPart` where each part wraps the *same* mesh with a different world matrix. The matrix-baking-into-vertices step naturally handles instancing. One render call. No renderer changes.

**Option B — multi-draw moderngl context.** Render N draws into one offscreen framebuffer. More efficient for high instance counts. Requires renderer changes.

For 80-125 unique meshes × ~hundreds of instance positions ≈ a few thousand triangles total (most building meshes are low-poly), Option A is fine. Bake everything into one big OBJ, render once.

Walker:
1. Discover the capital prefab via `load_capital_assets` (existing).
2. Find the prefab's `ClutterTransforms` MonoBehaviour (find by script class — see Phase 1; descend into nested children for Egypt).
3. Parse → list of `ClutterModel`.
4. Resolve each `mesh` PPtr and `material` PPtr to ObjectReaders. **PathID gotcha**: pathIDs in `globalgamemanagers.assets` collide with pathIDs in `resources.assets` — when resolving, look in `resources.assets` only. See `find_object_by_path_id` in `scripts/probes/render_clutter_mesh.py`:
   ```python
   def find_object_by_path_id(env, path_id):
       for fname, f in env.files.items():
           if "resources.assets" in fname and not fname.endswith(".resS"):
               target = f.objects.get(path_id)
               if target is not None:
                   return target
       return None
   ```
5. For each model, for each instance, build a `PrefabPart`. **PPtr-shape gotcha**: `bake_to_obj` calls `mesh_obj.deref_parse_as_object()`, but a parsed `PPtr` dataclass doesn't have that method. Wrap the resolved ObjectReader in an adapter (also from `render_clutter_mesh.py`):
   ```python
   class ObjectReaderAsPPtr:
       def __init__(self, reader): self._reader = reader
       def deref_parse_as_object(self): return self._reader.parse_as_object()
       def __bool__(self): return True
   ```
   Then: `PrefabPart(mesh_obj=ObjectReaderAsPPtr(mesh_reader), world_matrix=trs(instance.position, instance.rotation_euler, instance.scale), materials=[material_reader])`.
6. `bake_to_obj(parts, pre_rotation_y_deg=180.0)` → existing renderer.

**Diffuse texture extraction**: each capital has 1-2 shared materials (e.g., `GreeceMat`, `RomeTrim`). The existing `find_diffuse_for_prefab` walks each part's materials and picks the largest-area diffuse — this *should* work but assumes per-mesh materials. For ClutterTransforms (one shared material across all parts), it's simpler to look up the diffuse once from the single material. See `find_diffuse_texture_in_material` in `render_clutter_mesh.py` — it walks `m_SavedProperties.m_TexEnvs` for `_BaseColorMap`/`_BaseMap`/`_MainTex`/`_Albedomap`. Either path works; the latter is more direct for this case.

### Phase 3: wire into extractor

In `extract_improvement_meshes`, when a capital prefab walks to *no* `MeshFilter` leaves (the existing "no diffuse texture" skip path), route to `ClutterTransforms` rendering instead. Egypt is the edge case — its prefab has both an `Obelisk` (real `MeshFilter`) AND a `ClutterTransforms` — needs special handling: render both layered.

### Phase 4: tests

- Layout-drift smoke test: parse `Greece_Capital`, assert the parsed model count is in a reasonable range (3-10) and the first model's mesh resolves to `bigHome.001`.
- Per-nation rendering smoke test: render Greece, assert the output PNG has non-trivial content (not all-transparent, not all-one-color).
- Asset bundle change resilience: parser should fail loudly with a clear message if field layout drifts (don't return wrong data silently).

> The PVT hand-parser (background, not used by the Implementation plan above) followed the same approach with the `TerrainTexturePVTSplat` and `TerrainHeightSplat` field layouts — see [PVT hand-parsing requirement](#pvt-hand-parsing-requirement-resolved-investigation) below for the verified field layouts and PPtr resolution details. Same pattern (no embedded TypeTree → hand-parse binary against C# field layout) applies to `ClutterTransforms`.

## Open questions / risks

1. **List<> deserialization in nested structures.** Unity serializes `List<T>` as `int32 count` followed by N elements. `ClutterTransforms` has nested Lists (List<Model> at the outer level, each Model contains List<ClutterTransform>). The byte arithmetic must thread through both levels correctly; any off-by-one mid-stream and everything after misaligns. Smoke test by counting bytes consumed vs. body size.

2. **Field-layout drift across game versions.** Same risk as the original PVT plan: a Mohawk update that adds/removes/reorders `[SerializeField]` fields breaks the parser silently. Mitigation: smoke test asserting Greek mesh count and first-mesh name; fail loudly on body-size mismatch.

3. **Egypt's nested duplicate `Egypt_Capital` GO.** The Egyptian prefab has a child GameObject also named `Egypt_Capital` which carries the `ClutterTransforms` MonoBehaviour. `find_root_gameobject` does the right thing today (returns the parent with no Transform father), but the walker for finding the `ClutterTransforms` needs to descend into the child to find it.

4. **Egypt also has the Obelisk.** Real `MeshFilter` geometry (already extractable). The capital render should layer this on top of the clutter render — its position is in the prefab's transform hierarchy, not in `ClutterTransforms`.

5. **Material-from-pathID lookup.** PathIDs are unique per-asset-file, not globally. Resolving `mesh_pptr` and `material_pptr` from `ClutterTransforms` requires looking in `resources.assets`, not the first-loaded file. (The probe `render_clutter_mesh.py` documents this trap — see `find_object_by_path_id`.)

6. **`useStaticBatching` and tiling**. We're not currently using these flags but they're set on each ClutterTransforms. If a capital relies on `useWorldTiling` (e.g., the building set is meant to repeat across world space), our naive single-render approach might miss tiles. Verify by checking the parsed `useWorldTiling` flag — capitals should be `false` since each is a fixed location.

## Decisions already made

- **PVT splats are not the render path.** They paint dirt under the cities; the buildings live in `ClutterTransforms`. Verified via Egypt composite (`scripts/probes/composite_pvt.py` + side-by-side comparison) and via PPtr scan revealing the actual mesh roster.
- **Aksum + Hittite stay on the existing prefab walker** — full geometry baked into MeshFilter trees, no need to change anything.
- **The renderer doesn't need changes.** Verified by `scripts/probes/render_clutter_mesh.py` rendering 7 sample meshes through `bake_to_obj` + `render_mesh_to_image` with no modifications. The `ClutterTransforms` parser feeds a list of `(mesh, world_matrix, material)` tuples to the existing pipeline.
- **`load_object_by_path_id` must scope to `resources.assets`.** PathIDs in `globalgamemanagers.assets` collide with mesh pathIDs; loading globalgamemanagers first means the wrong objects come back if you don't filter.
- **`overrideMaterial` is the per-capital material.** Each `ClutterTransforms` has 1-2 materials max; `GreeceMat`, `RomeTrim`, etc. — these are shared across all the capital's meshes.

PVT-specific decisions (still valid for the *optional* terrain layer):
- Atlas mode unused everywhere.
- "Bull" GameObjects are no-ops (intensity 0.0 on a shared placeholder heightmap).
- Compositing order if we ever do PVT: ascending `sortingOffset`.
- Heightmap encoding: BC6H or BC4, both sample R.
- Babylon's `landBabylon_m` is BC5-encoded — needs special handling if PVT ever ships.

## Code references

Decompiled C# (read-only, from `~/Desktop/Old World/decompiled/Assembly-CSharp/`):

**Primary (ClutterTransforms — the building roster)**:
- `ClutterTransforms.cs:1-660` — the MonoBehaviour with the model list and instance transforms
- `ClutterTransforms.cs:155-206` — nested `Model` class (mesh + material + List<ClutterTransform>)
- `ClutterTransforms.cs:208-244` — top-level serialized fields (TilingProperties, models, etc.)
- `ClutterTransforms.cs:255-301` — `Regenerate()` showing how models are turned into per-instance draws
- `ClutterTransform.cs:1-30` — the per-instance struct (initialized + position + rotation + scale)
- `ClutterBase.cs:1-188` — base class (no `[SerializeField]` fields contributing to serialization)
- `ClutterRenderer.cs` — runtime instancing layer (not needed for our offline render path)

**Background (PVT splats — terrain layer, secondary visual)**:
- `TerrainTexturePVTSplat.cs:1-180` — the per-nation terrain albedo MonoBehaviour
- `TerrainTexturePVTSplat.cs:143-180` — `RefreshMaterial` showing all the shader property keys
- `TerrainHeightSplat.cs:1-178` — sibling component for heightmap stamps (also used by plinth fix)
- `TerrainSplatBase.cs:1-52` — base class (1 serialized field: `int sortingOffset`)
- `TerrainTextureRenderer.cs:1679-1748` — per-cell baking via orthographic cameras (in-game)

**City spawn entry**:
- `CityRenderer.cs:71-110` — `UpdateAsset` (runtime spawn entry point)
- `CityRenderer.cs:90` — `meCapitalAsset` lookup (which prefab gets instantiated)
- `CityRenderer.cs:94-101` — Walls/Moat/Towers spawned as separate sub-objects (not in our scope)

**Hex tile indirection (urban tiles)**:
- `Tile.cs:13013-13040` — `getUrbanAsset` (how surrounding tiles get nation-themed visuals)

XML chain for capital prefabs (in `Reference/XML/Infos/`):

- `asset.xml`, `asset-eoti.xml` — `ASSET_CITY_<NATION>_CAPITAL` entries with `Prefabs/Cities/<Nation>/<Nation>_Capital`
- `assetVariation.xml`, `assetVariation-eoti.xml` — `ASSET_VARIATION_CITY_<NATION>_CAPITAL` → SingleAsset

Pinacotheca code (current, no `ClutterTransforms` support):

- `src/pinacotheca/asset_index.py:load_capital_assets` — discovers the 12 capitals via XML chain (already works)
- `src/pinacotheca/extractor.py:extract_improvement_meshes` — routes capitals through the prefab walker; the 7 sparse ones cleanly skip with "no diffuse texture in prefab materials" (the skip path is where the new `ClutterTransforms` rendering should hook in)
- `src/pinacotheca/prefab.py:walk_prefab` — walks MeshFilter leaves; needs no change. The `ClutterTransforms` parser produces equivalent `PrefabPart` records that flow through `bake_to_obj` unchanged.
- `src/pinacotheca/prefab.py:bake_to_obj` — handles arbitrary list of `(mesh, world_matrix, materials)` parts. Will receive the parsed clutter instances directly.
- `src/pinacotheca/renderer.py:render_mesh_to_image` — current 3D renderer; **no changes needed** (verified by `scripts/probes/render_clutter_mesh.py`).

Working probes (in `scripts/probes/`):

- `parse_pvt_splat_binary.py` — verified PVT splat hand-parser (background; not the render path)
- `parse_urban_pvt.py` — same parser run across urban tiles (background)
- `extract_pvt_textures.py` — extracts source PVT textures as PNGs (background)
- `composite_pvt.py` — composites albedo × alpha for visual sanity check (background — produced the "Egypt is grass with sand patches" image that killed the PVT-only direction)
- `scan_clutter_meshes.py` — brute-force PPtr scanner; produced the verified per-capital mesh inventory
- `render_clutter_mesh.py` — single-mesh render through existing pipeline; produced the working 7 sample renders that proved the renderer needs no changes

## Won't-build alternatives considered

- **PVT splat renderer alone** — investigated thoroughly, found to produce only "per-nation dirt patterns under the city" without the buildings. The buildings live in `ClutterTransforms`, not in PVT.
- **2D perspective transform on the raw albedo** — tested, looks like a tilted 2D map poster.
- **Re-implement the full game terrain shader** — too much work for marginal benefit; even if it worked, you'd still be missing the buildings.
- **Render the alpha-masked albedo as a flat tile** — flat, no shading, no buildings.
