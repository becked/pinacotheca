# Runtime-Composed Nation Capitals

## Status: not implemented — design notes for a future iteration

## The problem

Old World has 12 nation capitals. Five render correctly via our normal prefab pipeline:

| Nation | Source | Why it works |
|---|---|---|
| Maurya | EOTI DLC | Full city geometry baked into one prefab |
| Tamil | EOTI DLC | Full city geometry baked into one prefab |
| Yuezhi | EOTI DLC | Full city geometry baked into one prefab |
| Aksum | base game | Full city geometry baked into one prefab |
| Hittite | base game | Full city geometry baked into one prefab |

Seven render incorrectly or not at all because their Capital prefab is essentially empty:

| Nation | What's actually in the prefab |
|---|---|
| Greece | 1 splat plane (`SplatTextureDefaultPVT` + alphamap) |
| Persia | 1 PVT splat + 1 height splat |
| Rome | 4 splat planes (PVT + height + clutter) |
| Carthage | 3 splat planes |
| Babylonia | 1 LakeWater plane + 3 splat planes |
| Assyria | 1 LakeWater plane + 3 splat planes |
| Egypt | 1 obelisk + 1 LakeWater plane + 3 splat planes |

These prefabs have no actual city geometry. The city you see in-game is composed at runtime from per-nation terrain textures painted onto the terrain mesh via Unity's render-to-texture system. We can't reproduce this in our isolated PNG render without re-implementing a chunk of the game's rendering pipeline.

## Scope: urban tiles too

Urban tiles (the surrounding hex tiles of any city — the city's "sprawl") use the **same** PVT composition pattern. We confirmed by inspecting every `*_Urban` prefab in the asset bundle:

- Aksum, Hittite, Greece, Rome, Persia, Egypt, Carthage, Babylonia, Assyria — every base-game `*_Urban` prefab is one splat plane, identical pattern to the sparse capitals.
- The three Indian DLC nations (Maurya, Tamil, Yuezhi) don't even have separate urban prefabs — they share a single `India_UrbanTile`, also one splat plane.

The asset team's choice pattern across all city-related geometry:

| Asset class | Approach | We render today? |
|---|---|---|
| Improvements (Library, Temple, Bath…) | Baked 3D mesh | Yes — via XML chain |
| Capitals: 4 DLC + Aksum + Hittite | Baked 3D mesh | Yes |
| Capitals: 6 base game | PVT runtime composition | No |
| Urban tiles: every nation | PVT runtime composition | No |
| Improvements: Farm, Mine, Pasture | PVT runtime composition (no clutter) | No |
| Improvements: Grove, Camp, Windmill | PVT + clutter splats | No (clutter unsupported) |

So implementing the PVT renderer (Phases 1-5 below) unlocks **both** missing capitals **and** all urban tile variants in one shot — roughly doubles the value of the future investment. Urban-tile texture references are included in the texture inventory table below; they reuse most of the same nation textures (with `*Urban*` variants).

## Improvements that share the splat pipeline

A handful of *improvement* prefabs use the same shader family as the sparse capitals — `Prefabs/Improvements/{Farm_Generic, Mine, Pasture, Grove, Camp, Windmill}` walk to nothing but `SplatTextureDefaultPVT` / `SplatHeightDefault` / `SplatClutterDefault` planes, with no static building geometry to extract. Discovered while debugging a per-ankh gap report (see commit log around 2026-04-27).

If/when the PVT renderer ships, **Farm, Mine, and Pasture come along for free** — they only use PVT + Height splats, which Phases 1–5 already cover. Two caveats:

1. **Different data path.** Capitals attach a per-nation `TerrainTexturePVTSplat` MonoBehaviour with custom albedo/normal/etc references. Improvements use the *shared default* `SplatTextureDefaultPVT` material applied directly to a Plane — there's no MonoBehaviour with per-improvement texture pointers. Phase 1's MonoBehaviour walker will return nothing on these prefabs and needs a second code path that pulls textures from the material's `m_TexEnvs` directly (`_Albedomap`, `_Alphamap`, `_Heightmap`).

2. **Clutter is the visual identity for three of them.** Grove, Camp, and Windmill are *clutter-dominant* — Windmill literally has no static mesh, just one height splat and one clutter splat where the runtime instantiates a windmill prop. Rendering these requires a clutter-splat phase (`Mohawk/Terrain/TerrainClutterSplat`) that the current plan doesn't cover. Tracked separately — see GitHub issue.

Render priority is debatable for the PVT-only set: a Farm rendered as a textured terrain patch (rows of crops painted onto dirt) is only marginally interesting next to the Library/Temple class of building renders. Worth shipping as a side effect of the capitals work, not as primary motivation.

## How the game composes them

Four stages, all in `decompiled/Assembly-CSharp/`:

### Stage 1 — authoring time (per-nation prefab properties)

Each Capital prefab contains `Plane` GameObjects with `TerrainTexturePVTSplat` MonoBehaviour components attached. The component holds per-nation properties (`TerrainTexturePVTSplat.cs:48-99`):

```csharp
public Texture albedoMap;        // e.g., GreeceCapTerrain
public Texture normalMap;        // e.g., greece_NRM
public Texture metallicMap;      // e.g., GreeceCapTerrain_M
public Texture roughnessMap;
public Texture alphaMap;         // e.g., GreeceurbanMask2 — footprint mask
public Color   albedoTint;       // optional per-nation color modulation
public float   normalMapIntensity;
public float   metallic, roughness;
public bool    materialUseWorldUVs;
public float   materialTiling;
public int     atlasIndex;       // alternative: pre-packed atlas mode
```

Each splat plane sits on the special Unity layer `TerrainTexturePVTSplat` (`TerrainTexturePVTSplat.cs:133`). Heightmap-bearing planes use `TerrainHeightSplat` layer (`TerrainHeightSplat.cs:10`). These layers are invisible to the main player camera.

### Stage 2 — runtime spawn (CityRenderer)

When a city is built, `CityRenderer.cs:90-93` does the standard:

```csharp
AssetVariationType assetVariationType = (cachedIsCapital
    ? infoNation.meCapitalAsset
    : infoNation.meCityAsset);
cityObject = gApp.RenderManager.SpawnAsset(assetVariationType, ...);
```

Just `Object.Instantiate`. The splat planes are now in the scene at their authored positions but invisible to the main camera (because of layers). Plus city projects (Walls, Towers, Moat — `CityRenderer.cs:94-101`) get spawned as separate sub-objects when the player builds them.

### Stage 3 — per-cell baking (the magic)

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

### Stage 4 — terrain mesh shading

The actual hex-tile terrain mesh has a shader that:
1. Samples `cellRenderTextureAlbedo` for color (now containing baked nation paint)
2. Samples `cellRenderTextureNormal` for surface direction
3. Samples `cellRenderTextureHeight` for vertex displacement (so painted "mountains" become actual height)
4. Blends with biome base textures (grass / sand / stone / snow underneath)
5. Applies PBR lighting

Result: ground beneath a Greek city has Greek mosaic patterns visible from any view angle, with proper shading and lighting, blended onto whatever biome (grassland, hills, coast) the city happens to sit on.

## Texture inventory per nation

Pull names — these are the textures attached to each nation's `TerrainTexturePVTSplat` components. To enumerate yourself: look in `resources.assets` for textures whose names contain the nation name. (See `extract_improvement_meshes` in `src/pinacotheca/extractor.py` for the UnityPy `Environment.load_file` + `os.chdir` bootstrap pattern.)

| Nation | Albedo | Height | Normal | Metallic/Roughness | Alphamap (footprint mask) |
|---|---|---|---|---|---|
| Greece | `GreeceCapTerrain` (2048²) | `GreeceCapTerrain_H` | `greece_NRM` | `GreeceCapTerrain_M` | `GreeceurbanMask2` (512²) |
| Greece urban | `GreeceurbanTerrain2b` (1024²) | (shared) | (shared) | (shared) | `GreeceurbanMask2` |
| Persia | `persiaCapPVT` (1024²) | (in `persia_UrbanPVT`?) | `persia_NRM` | — | `persia_capMask` |
| Persia urban | `persia_UrbanPVT` | — | — | — | `persia_UrbanMask` |
| Carthage | `Carthagepvt` (1024²) | — | `CityTrim_CarthageNRM` | — | `Carthagepvt_mask` |
| Carthage urban | `carthageUrbanPVT` | — | — | — | `carthageUrbanMask` |
| Egypt | (no `*Cap*` diffuse — uses `landEgypt_*`) | `landEgypt_height` | — | — | `landEgypt_Mask` |
| Egypt urban | (no diffuse — uses `landEgyptU_roads`?) | — | — | — | `landEgyptU_Mask` |
| Assyria | `AssyriaCapTerrain` (2048²) | `AssyriaCapH` | `assyria_NRM`, `assyria_NRM2` | — | `AssyriaCapmask` |
| Assyria urban | `AssyriaTerrain` (1024²) | — | — | — | `AssyriaUrbanmask` |
| Rome | (no separate diffuse — uses heightmap+normal) | `RomeGroundHeight` | `RomeGroundNormal` | — | (?) |
| Rome urban | `RomeUrban_H`, `RomeeurbanSet3UV_EgyptTrim_AlbedoTransparency` | `RomeUrban_H` | `RomeeurbanSet3_NRM` | — | `RomeMoatMask` |

Notable irregularities:
- **Egypt** uses `landEgypt_*` naming instead of `*Cap*`. Different artist convention.
- **Rome** has no `*Diffuse` — its color may come entirely from height + normal + base biome. Needs investigation.
- **Carthage** + **Babylonia** also have `LakeWater` planes (cothon harbor visualizations) that need filtering.
- All file sizes vary (512² – 2048²); the renderer needs to handle arbitrary input sizes.

## Why our screenshots looked unimpressive

The raw `GreeceCapTerrain` texture viewed straight-on is just the *input*. It's missing:
1. **Multiplied by the alphamap** — should be cropped to a hex-ish footprint, not edge-to-edge
2. **Normal map shading** — the bumps on the painted "mountains" are flat color in the texture; the normal map is what gives them lighting-direction info that makes them look 3D
3. **Heightmap as vertex displacement** — those bumps would be REAL geometric height, not paint
4. **Blended with biome base** — surrounding grass/dirt would feather into the city paint at the edges
5. **Proper PBR lighting** — directional sun lighting at the right angle, with the normal map driving per-pixel highlights

A 30° perspective tilt alone (which we tested) doesn't help — it just makes the flat poster look like a tilted poster.

## Implementation plan for a future iteration

Estimated effort: 3-5 days of focused work.

### Phase 1: extract the per-nation texture references (1 day)

Extend `prefab.py` (or a new `pvt_splat.py` module) to walk the prefab and collect the `TerrainTexturePVTSplat` MonoBehaviour properties. Returns something like:

```python
@dataclass(frozen=True)
class PVTSplat:
    plane_world_matrix: NDArray[np.float64]  # for positioning the plane in the bake
    albedo_map: Image.Image | None
    normal_map: Image.Image | None
    metallic_map: Image.Image | None
    roughness_map: Image.Image | None
    alpha_map: Image.Image | None
    albedo_tint: tuple[float, float, float, float]
    normal_intensity: float
    material_tiling: float
```

UnityPy MonoBehaviour reading for custom (non-built-in) script types is sometimes flaky. The `TerrainTexturePVTSplat` MonoBehaviour might not have an embedded TypeTree; in that case, use UnityPy's `read_typetree` or manual binary parsing using the field layout from the decompiled C# source.

Sanity check: the field order in the serialized binary should follow the `[SerializeField]` declaration order in `TerrainTexturePVTSplat.cs:48-99`.

### Phase 2: a minimal PBR-lite renderer (1-2 days)

In `renderer.py`, add a render mode for "ground tile":
- Hex or square plane mesh (tessellated for displacement — try 64×64 or 128×128 vertices)
- Vertex displacement: sample the heightmap, displace Y by `intensity * heightmap.r`
- Fragment shader:
  - Sample albedoMap × albedoTint (modulated)
  - Sample normalMap (decode from RG to XYZ; apply `normalMapIntensity`)
  - Sample alphaMap from the `alphaMapChannel` (R/G/B/A)
  - Lambertian + Blinn-Phong lighting from a fixed directional sun
  - (Skip metallic/roughness for v1 — full PBR is a rabbit hole)
- Camera: same 30° tilt + 45° FOV as buildings, framed to fill the image

Output: `IMPROVEMENT_3D_GREECE_CAPITAL.png` matching gallery aesthetic.

### Phase 3: biome blending (optional, 1 day)

For visual consistency, blend the alpha-masked nation paint over a biome base color. Pick a default biome (grass green) or sample it from a reference asset like `Grass_Tile_01_basecolor`. The alphamap controls the blend.

### Phase 4: wire into extractor (half day)

In `extract_improvement_meshes`, when a capital prefab has only splat planes (no real geometry), route to the ground-tile renderer instead of skipping. Use the discovery list from `load_capital_assets` plus a check on the prefab's actual geometry.

### Phase 5: tests (half day)

Synthetic tests for the PVTSplat extraction (using fake MonoBehaviour data structures) plus a visual smoke test that asserts the output PNG isn't all-transparent for a known input.

## Open questions / risks

1. **MonoBehaviour reading.** UnityPy can read built-in component types reliably but custom script types depend on whether a TypeTree is embedded. We may need to read the binary directly, using the field layout from `TerrainTexturePVTSplat.cs`. Risk: serialization order may have shifted across game versions.

2. **Multiple splat planes per prefab.** Greece_Capital has 1 plane but Rome_Capital has 4. Each plane has its own albedo/normal/etc. The render pipeline needs to composite multiple planes into one image — bake them in z-order (probably in the same order as `walk_prefab` returns them).

3. **Atlas mode.** `TerrainTexturePVTSplat.cs:46-55` shows there's an alternative "packInAtlas" mode using `albedoAtlas`/`alphaAtlas`/`normalMetalicRoughnessAtlas` + an `atlasIndex` to look up which slice. Probably not used by the per-nation capitals (they use simple mode), but worth checking if a render comes out blank.

4. **The custom splat shader.** The actual splat shader (the one that samples the per-nation textures and emits to the camera-rendered render texture) lives in compiled Unity assembly, not the decompiled C#. We have to reverse-engineer its behavior from the property setter calls in `RefreshMaterial` (`TerrainTexturePVTSplat.cs:143-180`). Keys to look for: `_Albedomap`, `_Normalmap`, `_Metallicmap`, `_Roughnessmap`, `_Alphamap`, `_AlphamapChannel`, `_AlbedoTint`, `_NormalMapIntensity`, `_MaterialTiling`, `_MaterialUseWorldUVs`. Behavior is straightforward (multiply albedo × tint, normal-decode then apply intensity, sample alpha from channel, multiply alpha into output).

5. **Heightmap encoding.** Some height textures are single-channel grayscale, some are RGB-packed. `TerrainHeightSplat.cs:54` shows `rgbHeightmap` is a thing — there may be RGB-encoded heightmaps with packed precision. Check texture format per file.

6. **Egypt edge case.** Egypt has both an obelisk (renderable as 3D geometry) AND a ground texture. May need to render both layered. Or just do the ground tile and skip the obelisk for consistency with other capitals.

7. **Aksum + Hittite — should they switch path?** Currently they render via the prefab walker because they have full city geometry baked in. If we add the ground-tile renderer, they'd ALSO have splat planes that could render. Decision: keep them on the prefab walker — they look great as-is, no need to change.

## Code references

Decompiled C# (read-only, from `~/Desktop/Old World/decompiled/Assembly-CSharp/`):

- `CityRenderer.cs:71-110` — UpdateAsset (the runtime spawn entry point)
- `CityRenderer.cs:90` — `meCapitalAsset` lookup
- `CityRenderer.cs:94-101` — city projects (Walls/Moat/Towers) spawned as sub-objects
- `TerrainTexturePVTSplat.cs:1-180` — the MonoBehaviour with all per-nation properties
- `TerrainTexturePVTSplat.cs:143-180` — `RefreshMaterial` showing all the shader property keys
- `TerrainTexturePVTSplat.cs:111-141` — `OnEnable` showing the shader uniform names
- `TerrainHeightSplat.cs:1-178` — sibling component for heightmap stamps (already understood, used by plinth fix)
- `TerrainTextureRenderer.cs:1679-1748` — `RenderCell` + `RenderCellSplats` (the per-cell baking pipeline)
- `TerrainTextureRenderer.cs:1690-1745` — the actual orthographic-camera-renders-PVT-layer pattern
- `Tile.cs:13013-13040` — `getUrbanAsset` (how surrounding tiles get nation-themed visuals)

XML chain for capital prefabs (in `Reference/XML/Infos/`):

- `asset.xml`, `asset-eoti.xml` — `ASSET_CITY_<NATION>_CAPITAL` entries with `Prefabs/Cities/<Nation>/<Nation>_Capital`
- `assetVariation.xml`, `assetVariation-eoti.xml` — `ASSET_VARIATION_CITY_<NATION>_CAPITAL` → SingleAsset

Pinacotheca code (current, no PVT support):

- `src/pinacotheca/asset_index.py:load_capital_assets` — discovers the 12 capitals via XML chain
- `src/pinacotheca/extractor.py:extract_improvement_meshes` — routes capitals through the prefab walker; the 7 sparse ones cleanly skip with "no diffuse texture in prefab materials"
- `src/pinacotheca/prefab.py:walk_prefab` — walks MeshFilter leaves; would need extension to also walk MonoBehaviour Components
- `src/pinacotheca/prefab.py:find_diffuse_for_prefab` — current texture lookup (won't find PVT splat textures)
- `src/pinacotheca/renderer.py:render_mesh_to_image` — current 3D renderer; would need a new `render_ground_tile` sibling

## Won't-build alternatives considered

- **2D perspective transform on the raw albedo** — tested with PIL on `GreeceCapTerrain.png`, looks like a tilted 2D map poster, not a 3D scene. Doesn't match gallery aesthetic.
- **Render the alpha-masked albedo as a flat tile** — no shading, fundamentally flat. Would feel out of place alongside the other 3D building renders.
- **Re-implement the full game terrain shader** — way too much work; would also need biome textures, sun direction matching, and the entire vertex-displacement pipeline. Days of work for marginal aesthetic improvement over the PBR-lite plan above.
