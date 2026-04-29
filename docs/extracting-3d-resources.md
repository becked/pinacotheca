# Extracting 3D resource icons (animals, ores, plants)

This doc captures everything we learned reverse-engineering Old World's
resource rendering, plus the conventions our extractor follows. If a
new resource looks wrong, start here.

For improvements, see `extracting-3d-buildings.md`. For ClutterTransforms
(sparse capitals, urban tiles), see `runtime-composed-cities.md`. For
the still-deferred ClutterSpawner system (Salt), see
`clutter-spawner.md`.

## What we render

- `RESOURCE_3D_<NAME>_SOLO.png` — the artist-authored "single rig"
  (one centered animal/object). Used by per-ankh on the map.
- `RESOURCE_3D_<NAME>_HERD.png` — the multi-rig herd that's the game's
  default appearance.
- For multi-creature prefabs (Crab, Fish), each variant is split by
  rig family: `RESOURCE_3D_CRAB_SOLO_CRAB.png`,
  `RESOURCE_3D_CRAB_SOLO_BIRD_SEAGULL.png`, etc.

## How the game does it

`ResourceRenderer.cs` (decompiled) spawns the resource prefab at the
tile's world position with `Quaternion.identity`. The prefab itself is
a tree of `Transform`s holding multiple rigs. The runtime then:

1. Reads the player's `GraphicsSettings.singleResourcesEnabled`.
2. Calls `EnableSingleObjectMode(enable=singleResourcesEnabled)`.
3. That method:
   - Searches for immediate children tagged `SoloResource`.
   - When `enable=true` (LOW/MINIMUM presets): `SetActive(false)` on
     all non-tagged immediate children → only the solo rig stays
     visible.
   - When `enable=false` (HIGH/MEDIUM, the default): `SetActive(true)`
     on all non-tagged immediate children → herd visible. Solo
     children's saved active state isn't touched.

`AnimationToggle.SetInitialState` runs each rig's Animator (with a
Generic Avatar). For animal rigs, this animates the bones — but does
not modify the rig root's local rotation
(`m_HasGenericRootTransform: False` on the idle clip; verified for
`Goat_Base_Idle_A`).

Each rig also carries a `TerrainPositioner` MonoBehaviour
(`decompiled/Assembly-CSharp/TerrainPositioner.cs`) that on `OnEnable`
and `TerrainPhysics.OnTerrainDataChanged` overrides the rig's
`transform.position.y` to `TerrainPhysics.PositionToTerrain(...)`.
This flattens herd Y to terrain height. We do not simulate this; we
use the prefab's saved Y values, which are usually within ~0.1 of zero.

## The Unity tag system in this game

`m_Tag` on a GameObject is an **int** (UnityPy doesn't expose
`m_TagString` for these prefabs). Old World user tags begin at int
**20000**, mapped via the TagManager in `globalgamemanagers` (no
`.assets` extension):

- `globalgamemanagers` is a separate `SerializedFile` from the
  `globalgamemanagers.assets` we already load for ClutterTransforms.
  Loading it adds the `TagManager` SerializedObject to the env.
- Read via `obj.read_typetree()`; `tags` is a flat list. The int is
  `20000 + index_in_tags`.
- "SoloResource" is at user-tag index 12 → `m_Tag = 20012`.

`_load_solo_resource_tag_ids(game_data)` in `extractor.py` resolves
this once at extraction start. The empty-frozenset fallback (when the
file is missing or doesn't parse) gracefully degrades to "no
SoloResource subtree on any prefab" — every resource then renders the
solo=herd content to both files.

## Mesh authoring is not consistent across animals

Different rigs have meshes authored along different axes. Verified via
`mesh.m_LocalAABB.m_Extent` (which is on the parsed mesh — no
`MeshHandler.process()` needed for this read):

| Mesh | Extent (X, Y, Z) | Body length axis | Notes |
|---|---|---|---|
| Goat | (0.36, 1.20, 1.68) | mesh +Z | upright author, Y is height |
| Cattle (CowDairy) | similar to Goat | mesh +Z | upright author |
| Sheep | similar | mesh +Z | upright author |
| Horse (`horse_01`) | (0.61, 2.52, 2.23) | mesh +Y | lying flat, body along Y |
| Pig (`Pig_GEO`) | (0.71, 2.19, 1.10) | mesh +Y | lying flat |
| Crab (`Crab_GEO`) | (0.22, 0.16, 0.13) | mesh +X (legspan) | flat, viewed from above |
| Fish (`FishSeaBass_*`) | (0.13, 0.33, 0.65) | mesh +Z | swimming, mesh +Y is ventral |
| Seagull (`Bird_Seagull_GEO`) | (1.20, 0.19, 0.54) | mesh +X (wingspan) | wings spread, flat |

Per-mesh dorsal axis ALSO varies. There's no single rotation that
works for all rigs.

## The rotation pipeline

Each PrefabPart's world matrix is built bottom-up by `walk_prefab`'s
recursion, then post-multiplied by `bake_to_obj`'s
`pre_rotation_y_deg=180` (a Y-axis flip — "meshes are authored facing
-Z, render from +Z"). The full chain for one mesh leaf is:

```
bake_Y180 · prefab_root_local · ... · rig_local · smr_local · vertices
```

Three levers we control:

### Lever 1 — `drop_animated_smr_rotation` (B-lite)

When the SMR's GameObject is under an `Animator` with a non-null
`Avatar`, we substitute identity for the SMR's saved local rotation.
Reason: the saved rotation is "editor pose" garbage that the runtime
animates over. Verified for Goat, Cattle, Sheep — dropping it leaves
them upright. Wrong for Horse/Pig/Crab/Fish, hence Lever 3.

This is a per-leaf decision made in `walk_prefab.recurse`. Always on
for resource jobs.

### Lever 2 — Tag filters (`exclude_tag_ids`, `include_only_tag_ids`)

Per-subtree filtering by Unity tag ID. Used to render the herd
(`exclude_tag_ids={SoloResource}`) and the solo
(`include_only_tag_ids={SoloResource}`) variants from the same
prefab. Implemented as ancestor-flag tracking in `walk_prefab.recurse`
(see `under_required_tag` thread).

The `include_only` filter is sticky: once we descend into a tagged
GO, all descendants are emitted regardless of their own tags. This
matches the runtime: `EnableSingleObjectMode` toggles only the
*immediate* tagged children; their entire subtrees go with them.

### Lever 3 — `rig_rotation_overrides`

Name-keyed map from rig family-name to a corrective quaternion. When
walked, a GameObject whose name matches gets its saved local rotation
**replaced** entirely (B-lite identity drop is bypassed too).

Family name derivation in `_go_name_family`:

```
"Horse_Rig_single"     → "Horse"
"Horse_Rig_2"          → "Horse"
"Bird_Seagull_Rig (3)" → "Bird_Seagull"
"Crab"                 → ""    (no _Rig — prefab roots don't match)
"Pig_GEO"              → ""    (mesh GO under rig)
```

The empty-string fallback for non-rig GameObjects is critical:
without it, prefab roots like "Pig" or "Crab" would derive family
"Pig"/"Crab" and get the override applied at root level too — which
double-applies the rotation when the rig also matches.

#### Current override values

```python
RIG_ROTATION_OVERRIDES = {
    "Horse":         (-0.5,  -0.5, -0.5,  0.5),  # Rx(-90°)·Rz(-90°)
    "Pig":           (-0.7071, 0.0, 0.0,  0.7071),  # Rx(-90°)
    "Fish_Sea_Bass": ( 0.5,   0.5, 0.5,  0.5),  # 120° around (1,1,1)/√3
    "Bird_Seagull":  ( 0.0,   0.7071, 0.0, 0.7071),  # Ry(+90°)
    "Crab":          (-0.7071, 0.0, 0.0,  0.7071),  # Rx(-90°)
}
```

The values were tuned empirically. Rationale per entry:

- **Horse**: prefab root is identity. Mesh +Y is body length, mesh +Z
  is dorsal. We want body across world X with back up. Rotation is
  `Rx(-90°)·Rz(-90°)`: maps mesh +Y → world +X (length horizontal),
  mesh +Z → world +Y (back up).
- **Pig**: prefab root has saved rotation `(180, -89, 180) ≡ Ry(91°)`
  that rotates the entire subtree. With the root's Ry(91°) compounded,
  a simple `Rx(-90°)` at the rig lands the body axis on world ±X (side
  view) — cleaner than re-deriving the full rotation that includes
  the root.
- **Fish_Sea_Bass**: prefab root is `(90, 0, 180)`. Plus mesh +Y is
  the ventral (belly) direction, not dorsal. The 120° rotation around
  `(1,1,1)/√3` permutes the axes correctly so body lies along world
  X with back up.
- **Bird_Seagull**: rig + root are both identity. Mesh is wingspan
  along X (1.20), length along Z (0.54), thinness along Y (0.19).
  `Ry(90°)` puts body length (Z) across screen and wings into the
  depth — side profile of a bird in flight.
- **Crab**: rig has a Y-spin we replace. `Rx(-90°)` puts the crab's
  shell-up axis (mesh +Z) at world +Y, giving a top-down crab view
  with legs spread.

### Tuning a new problem rig

1. Re-render. Look at the result.
2. Identify which mesh axis is body length, which is dorsal, which is
   left/right. Use `m_LocalAABB.m_Extent` plus the visual.
3. Pick a target world layout (usually: body length along ±X, dorsal
   at +Y, lateral along ±Z).
4. Solve for `R_override` such that `R_bake · R_root · R_override`
   maps mesh axes to the target. `R_bake = Ry(180°)`. `R_root` is the
   prefab root's saved rotation (read it from the dump).
5. Convert R to quaternion. Add to `RIG_ROTATION_OVERRIDES`.
6. Re-render and verify.

The `scripts/dump_prefab.py` script (extended in this session) prints
each GO's tag and saved euler rotation, useful for step 4.

## Multi-rig split

Triggered when a resource prefab has 2+ immediate children tagged
`SoloResource`. Currently only Crab and Fish trigger it.

`_classify_immediate_children` in `extractor.py` splits the immediate
children into `solo_children` and `herd_children` lists, each a list
of `(family_name, child_go)` pairs. The render loop then walks each
family separately with `parent_world=root_local` (so the prefab root's
TRS is applied — `walk_prefab(child_go)` would otherwise miss it).

`_derive_rig_family` strips ` (N)` and `_single` suffixes, then takes
everything before `_Rig`. Same family-name space as
`rig_rotation_overrides` (intentional — the same family is tagged
the same way in both).

ClutterTransforms parts are computed once per prefab and added to
**every** family render in the split path. CT is a separate
composition system from rigs and isn't tag-filtered. (No multi-rig
prefab currently has CT, but the logic is symmetric for safety.)

## Camera and projection

For all `force_upright=True` jobs (improvements + resources):

- **Orthographic projection**, 30° downward tilt, distance =
  `max_extent * 1.6`, frustum half-size = `max_extent * 0.66`.
- The game uses perspective + far camera, but on any single hex the
  perspective approximates ortho (the back-row goat at world Z=-2 is
  ~28 units from the in-game camera vs ~30 for the front-row;
  perspective foreshortening is ~7%, visually invisible). Switching
  our renderer to ortho matches what the game shows on a single hex
  while keeping our atlas-tile-tight framing.
- `bake_to_obj(pre_rotation_y_deg=180.0)` applies a final Y-flip to
  every job (improvements and resources). This is a camera convention
  ("meshes authored facing -Z, render from +Z") not a per-job tweak.

If the camera angle ever needs tuning per-job, change
`render_mesh_to_image`'s `force_upright` branch in `renderer.py`.

## Shader: alpha-cutout

The fragment shader (`renderer.py`) applies `if (tex_color.a < 0.5)
discard;` before writing to the framebuffer. Required for any
mesh that uses alpha-cutout textures — tree-leaf billboards,
scrub plants, the Yuezhi capital's tree decorations. Without
it, transparent fragments still write to the depth buffer and
render as opaque rectangles where the texture is supposed to be
see-through.

Threshold 0.5 matches Unity's standard cutout shader. Safe for any
opaque texture (alpha=1 passes). Drops semi-transparent surfaces
(alpha=0.3) — Old World resources don't use those for static
decoration.

## File naming and downstream contract

`extracted/sprites/resources/RESOURCE_3D_<NAME>_<VARIANT>.png` where
VARIANT is one of:

- `SOLO` (single-rig prefabs) — central single animal/object.
- `HERD` (single-rig prefabs) — the herd group.
- `SOLO_<FAMILY>` (multi-rig prefabs) — solo for one family.
- `HERD_<FAMILY>` (multi-rig prefabs) — herd for one family.

For prefabs with no `SoloResource`-tagged subtree (Stone, Citrus,
Salt, etc.), we render once and save the same image to both `_SOLO`
and `_HERD`.

Per-ankh keys on these filenames. Renaming is a breaking change
across both repos.

## What we don't render correctly yet

- **Salt**: missing the deposit-chunks scatter. `Salt_Deposit_Chunks`
  carries a `ClutterSpawner` MonoBehaviour (procedural runtime
  spawning), not a `ClutterTransforms`. We don't support
  ClutterSpawner. See `clutter-spawner.md` for the deferred-fix
  notes.
- **Iron, Gem, Gold, Silver, Wheat, Barley, Sorghum, Honey,
  Lavender, Olive, Wine, Dye**: skip with "no usable mesh parts" or
  "no diffuse texture". These prefabs likely follow yet-other
  composition patterns we haven't decoded; some may be CS-only too.
- **Incense**: renders nearly empty — visible scrub fragments are
  tiny dots after autocrop. The prefab content is genuinely sparse;
  not a renderer bug.
- **TerrainPositioner Y normalization** — herd rigs render at slightly
  different Y values (~0.1 unit variance) because we use saved Y
  rather than the runtime terrain-snap. Not visually significant for
  icon use.

## Useful diagnostic scripts

- `scripts/dump_prefab.py` — recursive prefab tree dump with euler
  rotations, tags, and component types. Use when adding a new override
  or diagnosing an orientation problem.
- `scripts/inspect_animal_mesh.py` — mesh AABB extents per animal,
  Animator controller and clip resolution. Use when verifying which
  axis is body length.
- `scripts/verify_skinned_mesh.py` — bind-pose vs prefab-pose
  comparison, written when investigating B-lite. Useful if a future
  animal turns out to be skinned (m_Bones non-empty); none of the
  current resource animals are.

All three live in `scripts/` and probe the live game data via
`pinacotheca.extractor.find_game_data()`. Read-only; safe to run any
time.

## Decompiled C# references

- `decompiled/Assembly-CSharp/ResourceRenderer.cs` — the runtime
  resource render path; especially `EnableSingleObjectMode`
  (line 141) and `UpdateAsset` (line 76).
- `decompiled/Assembly-CSharp/RenderManager.cs` — `SpawnAsset` and
  `InstantiatePrefab`. Confirms the prefab root is spawned at
  `Quaternion.identity` and `aiValidRotations` Y-rotates the parent
  container only.
- `decompiled/Assembly-CSharp/AnimationToggle.cs` — only manipulates
  `Animator.enabled`; no transform writes.
- `decompiled/Assembly-CSharp/TerrainPositioner.cs` — Y-only position
  override on each rig.
- `decompiled/Assembly-CSharp/ClutterSpawner.cs` — the procedural
  spawner system Salt uses; not yet supported.
