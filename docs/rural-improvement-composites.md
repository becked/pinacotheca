# Rural-Improvement Composites

## Status: Group A shipped; Group B deferred

`extract_rural_composite_meshes` (in `src/pinacotheca/extractor.py`) renders a per-(improvement, resource) composite for every rural improvement that ships a **per-resource merged prefab** — Farm+Barley, Mine+Gold, Grove+Wine, etc. Output filenames: `IMPROVEMENT_3D_<NAME>_<RESOURCE>.png` in `extracted/sprites/improvements/`.

Unlike the urban composites, these embed **no biome ground hex**. per-ankh keeps drawing its own `TERRAIN_3D_<biome>_<height>.png` underneath these PNGs, so the composite is biome-agnostic — a Mine+Gold on Lush hill terrain shows correctly because per-ankh layers the Lush hill tile under it.

The merged prefab's own `TerrainTexturePVTSplat` planes (`<find_pvt_splats_in_prefab>`) ARE included — these encode each improvement's tile-local painted ground (the wheat/barley/sorghum field, the mine excavation patch, the dirt around the lumber mill). They're transparent outside the painted area, so per-ankh's biome hex still shows around the field. The PVT painting is intrinsic to the improvement's identity, not biome ground; including it is the difference between a Farm_Barley render that shows just buildings versus one that shows a wheat field with buildings on it.

The existing bare-improvement renders (`IMPROVEMENT_3D_<NAME>.png`) and bare-resource renders (`RESOURCE_3D_<NAME>.png`) are preserved untouched. per-ankh prefers the composite when both `(tile.improvement, tile.resource)` exist on a tile AND a composite for that pairing was generated; otherwise falls back to drawing the bare improvement + bare resource separately.

## What it produces

**23 PNGs** (Group A only — see "Why Group B is deferred" below):

- **Farm**: BARLEY, SORGHUM, WHEAT (3)
- **Mine**: IRON (zIcon for ORE), GOLD, GEM, SILVER, SALT, JADE (6)
- **Quarry**: STONE (zIcon for MARBLE) (1)
- **Lumbermill**: EBONY (1, EOTI DLC)
- **Grove**: CITRUS, HONEY, INCENSE, LAVENDER, OLIVE, WINE, SPICES, SILK (8)
- **Nets**: FISH, CRAB, DYE, PEARL (4)

Pasture (HORSE/CATTLE/SHEEP/PIG/GOAT — 5) and Camp (CAMEL/ELEPHANT/FUR/GAME — 4) compose into 9 deferred Group B pairs. `load_rural_composite_pairs` still discovers these from XML; `extract_rural_composite_meshes` filters them out at render time.

## Why two render groups exist (and why we ship only one)

The game runtime splits rural rendering two ways (`decompiled/Assembly-CSharp/ImprovementRenderer.cs:487` and `ResourceRenderer.cs:88-90`):

- **Group A — per-resource merged prefab**: improvement.xml's `aeResourceAssetVariation` maps `resource → bespoke prefab` (e.g. `Mine_gold`, `Farm_Barley`, `Grove_Wine`). The runtime swaps to the merged prefab, and `ResourceRenderer` returns early — no separate resource prefab is spawned. So the Group A merged prefab visually IS the improvement+resource composite. We walk it and bake once. **This works cleanly offline.**

- **Group B — improvement prefab + resource prefab spawned independently**: Pasture and Camp don't have `aeResourceAssetVariation`. The game spawns the bare improvement prefab AND the resource prefab at the same tile center; the herd of horses/cattle/etc. lives in the resource prefab while the fence/camp structure lives in the improvement prefab. **This DOES NOT work cleanly offline** — see below.

## Why Group B is deferred

Resource animal prefabs (Horse, Cattle, Sheep, Pig, Goat, Camel, Elephant, Deer, etc.) use Unity's **Optimized GameObject Hierarchy** + **Mecanim Animator**. The mesh's `m_Bones` array is empty; bones live inside the Avatar asset. The bind pose stored in the Avatar's `m_DefaultPose` is identical to `m_AvatarSkeletonPose` — both store the rest pose, which for these rigs is **not standing**. The standing/idle pose is only realized at runtime when the AnimatorController plays the idle clip.

That idle pose is stored exclusively in the AnimationClip's `m_MuscleClip` (`ClipMuscleConstant`), Unity's compressed Mecanim format. UnityPy has no helper to sample it — confirmed by `dir(AnimationClip)` (only `save` / `load`, no curve sampling). Decompressing it requires reverse-engineering Unity's MecAnim runtime. That work is out of scope for this feature.

Without the idle pose:

- Pasture+Horse: the existing `RIG_ROTATION_OVERRIDES["Horse"]` (a portrait-icon hack designed for the standalone `RESOURCE_3D_HORSE_HERD.png` view) puts every horse in the same orientation, so for a 3-horse herd in a pasture, all horses face the same direction and the rightmost one extends past the fence (X extent 8.94 vs pasture footprint 7.77).
- Camp+Game: the Deer rig isn't in the override map at all — two of three deer render flat on their sides, and one is authored at `localY=+2.03`, so it floats well above the camp.

We tried four alternatives — keeping rig rotation, dropping it, multiplicative composition, sampling Avatar bind pose via CPU skinning — none produce upright animals at correct positions. See `/tmp/pasture_horse_*.png` test renders.

The path forward when revisiting Group B: implement Mecanim muscle clip sampling (or vendor it from a project like AssetStudio / AssetRipper that has done this). Once the idle pose can be applied to bones offline, CPU skin the herd mesh, then bake with shared bbox alongside the improvement layer (the `extract_rural_composite_meshes` skeleton already supports a two-layer call to `render_layered_ground`).

## Pair discovery

`load_rural_composite_pairs(xml_dir)` in `src/pinacotheca/asset_index.py` is the canonical source of truth and **still returns both groups**. Only the extractor filters Group B at render time — keeping discovery group-agnostic means tests and downstream callers see the full XML truth.

The discovery rule:

1. Walk every improvement entry across `improvement.xml` + DLC siblings (`improvement-event.xml`, etc.).
2. Look up the improvement's `<Class>` in `improvementClass.xml` (+ DLC). If the class has non-empty `<abResourceValid>` (Pairs with `bValue=1`), iterate the valid resources.
3. For each (improvement, resource):
   - Try Group A first: if the improvement has `aeResourceAssetVariation[resource]`, resolve it through the standard `assetVariation.xml → asset.xml` chain. If a prefab name is found → emit Group A pair (`resource_prefab_name=None`).
   - Else (or if the Group A chain fails): try Group B. Resolve the improvement's base `<AssetVariation>` to a prefab name AND look up `RESOURCE_<X>.AssetVariation` in `resource.xml` and resolve that. If both resolve → emit Group B pair (with `resource_prefab_name` set).
   - Otherwise skip with a debug log.
4. Dedupe on `(improvement_z_icon_name, resource_z_icon_name)`. Both keys use `zIconName` (post-alias), not `zType` — so `RESOURCE_ORE` collapses with `RESOURCE_IRON` (same zIcon=`RESOURCE_IRON`), and `IMPROVEMENT_LAURION_MINE` (event-pack) collapses with `IMPROVEMENT_MINE` (both zIcon=`IMPROVEMENT_MINE`).

The Wine quirk is handled automatically: `IMPROVEMENT_FARM` has `aeResourceAssetVariation[RESOURCE_WINE]` mapping to a Farm_Generic prefab, but `IMPROVEMENTCLASS_FARM.abResourceValid` does NOT include Wine. Wine is a Grove resource. The class-list filter rejects Farm+Wine; Grove+Wine resolves separately to `Grove_Wine`.

## How a Group A composite is built

Per pair:

1. **Walk the merged prefab**: `MeshFilter` parts (LOD-filtered, splat-filtered) + ClutterTransforms expansion. Farm, Mine, Grove all encode some or all of their content via `ClutterTransforms`, so the walker uses the same expansion path as the urban composites.
2. **Find the prefab's PVT splat planes** via `find_pvt_splats_in_prefab`. These are the painted ground patches intrinsic to the prefab.
3. **Render**: `render_layered_ground(primary_parts, pvt_planes, None, env)`. With `biome_base=None`, the orchestrator skips the biome rescale and biome render; PVT planes compose and render as a layer underneath the buildings. Transparent bg.
4. **Sidecar**: `composition="layered"` when PVT planes are present (the bbox covers the prefab + its own painted ground patch); `"prefab"` when no PVT (only NETS variants today).

## Filenames and per-ankh integration

`IMPROVEMENT_3D_<improvement_zIconName>_<resource_zIconName>.png` — both names with their `IMPROVEMENT_` / `RESOURCE_` prefixes stripped:

- `IMPROVEMENT_3D_FARM_BARLEY.png`
- `IMPROVEMENT_3D_MINE_GOLD.png`
- `IMPROVEMENT_3D_MINE_IRON.png` (RESOURCE_ORE → IRON via zIconName alias)
- `IMPROVEMENT_3D_QUARRY_STONE.png` (RESOURCE_MARBLE → STONE)
- `IMPROVEMENT_3D_GROVE_WINE.png`
- `IMPROVEMENT_3D_NETS_FISH.png`

per-ankh's lookup (separate change in the per-ankh repo): when rendering a tile, prefer `IMPROVEMENT_3D_<imp>_<res>.png` if both `tile.improvement` and `tile.resource` are set and the composite exists. Fall back to drawing `IMPROVEMENT_3D_<imp>.png` + `RESOURCE_3D_<res>.png` separately when no composite exists — that's the path Pasture+animal and Camp+animal tiles will use until Group B ships.

These outputs are NOT layered with biome — per-ankh keeps drawing the `TERRAIN_3D_<biome>_<height>.png` underneath rural composites just as it does for bare improvements today.

## What's not extracted

- **Drought / hurricane state variants**: `assetVariation.xml` ships `ASSET_VARIATION_IMPROVEMENT_FARM_DROUGHT` etc. as weather-state alternates of the base variations. Out of scope — not new pairs, just visual states of existing pairs.
- **Embedded biome ground**: explicitly rejected during planning. Rural tiles aren't biome-locked at the data level, and per-ankh already layers terrain underneath. Locking the composite to a single biome would mean a Lush map shows a Temperate hex under every Pasture.
- **Group B (Pasture+animal, Camp+animal)**: deferred pending Mecanim muscle clip sampling — see "Why Group B is deferred" above.
