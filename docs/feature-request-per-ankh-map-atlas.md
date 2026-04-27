# Feature Request: Per-Ankh Map Atlas

Source: per-ankh's hex-based map renderer (the "Map Beta" view). Per-Ankh bakes pinacotheca-extracted PNGs into a hex-clipped + scaled atlas (`scripts/bake-atlases.ts`) and composites them onto a terrain layer with deck.gl. We tested two improvements (Library, Granary) end-to-end and identified what works, what doesn't, and what changes upstream in pinacotheca would close the gap.

This doc supplements [`extracting-3d-buildings.md`](./extracting-3d-buildings.md) — much of what's described there as "option considered" is now an active per-ankh need.

## What works today

- **Granary-style multi-component prefabs** render correctly. We initially thought the side jar-on-platform clusters were extraneous "variants" and tried cropping them; on comparison with in-game zoom screenshots, those clusters are actual structural pieces of the granary. Pinacotheca's prefab walk is doing the right thing here.
- **Pure single-piece improvements** without baked plinths render cleanly and drop into a hex naturally.
- **Transparent backgrounds** are clean enough that we can composite over our terrain hexes without halos.

## What doesn't work, and what we need

### 1. Plinth stripping (HIGH)

**Problem.** Library, Christian Temple, and similar single-piece improvements have a stone foundation/slab baked into the mesh. When per-ankh composites these on a terrain hex, the plinth doubles up with the underlying terrain — visually it reads as "stone slab on top of grass" rather than "building rooted in the tile."

In pinacotheca's atlas the plinth often dominates: for `Library_LOD0` the doc notes "bottom 5% of vertical extent covers its full XZ footprint." In our render that bottom 50%+ of pixels is plinth, with the actual library building (cube + dome) compressed into the top half. After per-ankh's hex-fit scaling, the building is small and the plinth is jarring.

**Per-ankh preferred fix.** Option 1 from `extracting-3d-buildings.md`: strip the built-in plinths so every building is a "floating portrait." Per-ankh's terrain layer is the ground; we don't need pinacotheca to provide one.

**Suggested implementation.**
- Heuristic auto-detect: if a mesh's bottom 5% of vertical extent covers ≥ 80% of its full XZ footprint, treat as plinth and trim those vertices.
- OR per-asset config file (`plinth_strip.toml`?) listing meshes to strip and their cut height.
- Heuristic is cheaper and probably right for the 95% case; config catches edge cases.

**Acceptable visual loss.** The doc flags this as "loses the visual richness of the Library and Christian Temple bases." We've decided that's a fine trade — the per-ankh map gets richness from the surrounding terrain and adjacent urban tiles, not from each building's plinth.

### 2. Per-family / per-culture asset variants (HIGH)

**Problem.** The game ships multiple visual variants of the same improvement, keyed on the player's family/culture. A Tamil library is a green-domed white-trimmed temple-style building; an Egyptian library (or whatever pinacotheca currently extracts) is a tan stone box with a small dome — they're visibly different buildings. Pinacotheca currently exports one mesh per improvement, so we render every culture's library with the same asset and it looks wrong for ~half of them.

**Per-ankh need.** For each (improvement, family) tuple where the game has a distinct mesh, an isolated render named accordingly. Examples:

```
IMPROVEMENT_3D_LIBRARY_FAMILY_TRADER.png        (Tamil/Indus etc.)
IMPROVEMENT_3D_LIBRARY_FAMILY_PATRON.png        (Egyptian-style)
IMPROVEMENT_3D_LIBRARY_FAMILY_HERO.png          (Greek-style)
...
```

Naming TBD — whatever matches how the game keys them in source. Per-ankh would consume by looking up `(tile.improvement, owner_player.family)` and falling back to the bare `IMPROVEMENT_3D_LIBRARY.png` if no variant exists.

**Investigation hint.** Look in `decompiled/Assembly-CSharp` for how the game picks an improvement mesh at render time — there's likely a switch on family/culture/nation that points at different prefabs or different child GameObjects. Granary may not have variants (it's culturally-neutral); library, monastery, palace, capital almost certainly do. The DLC capitals (Maurya/Tamil/Yuezhi) are already family-specific and `extract_composite_meshes` handles them — same machinery may extend.

### 3. Splat-shader Plane meshes on composite prefabs (MEDIUM)

**Problem.** Composite prefabs (`Maurya_Capital`, `Tamil_Capital`, `Yuezhi_Capital`, `AksumCapitol`, `Hanging_Garden`, `Kushite_Pyramid`, `Pyramid_lvl_1`–`4`) ship companion `Plane` meshes for the courtyard. These use Old World's custom terrain splat shader (heightmap + alphamap blended at runtime). Pinacotheca falls back to plugging the alphamap into a standard textured-mesh shader, producing scrambled-hieroglyph artifacts at the courtyard floor.

The same issue affects some prefab-walked improvements that have splat-Plane children (`Watermill`, `Market` in our checks).

**Per-ankh preferred fix.** Option 1 from `extracting-3d-buildings.md`: skip Plane meshes whose materials are `SplatHeightDefault` / `SplatTextureDefaultPVT` / `WaterNoFoam`. Building "floats" without its courtyard, but combined with #1 above (no plinth) and per-ankh's terrain layer beneath, the visual gap is small.

**Implementation hint.** In `prefab.py`'s `walk_prefab`, filter `MeshFilter` leaves whose first material name matches a splat-shader pattern. Alphabetical first match works:

```python
SPLAT_SHADER_PATTERNS = (
    "SplatHeight", "SplatTexture", "WaterNoFoam",
)
def is_splat_plane(materials):
    return any(p in (m.name or "") for m in materials for p in SPLAT_SHADER_PATTERNS)
```

**Alternative** (option 2 in the existing doc): synthesize a grass tile underneath. Useful if certain wonders look bad floating, but per-ankh's terrain layer should make this unnecessary for the common case.

## Lower priority / nice-to-have

### Camera angle parity with the game

Pinacotheca currently renders at 30° tilt with 45° FOV, framed tightly. The game uses 45° tilt, 45° FOV, far camera distance. The shallower angle was a deliberate choice to give a clearer 3/4 view at close framing.

For per-ankh's map this hasn't been a problem so far — we composite at hex scale where the angle difference is barely perceptible. **No action requested**, just noting that if a future per-ankh use case (e.g., higher-zoom map mode) needs a tighter game-camera match, this becomes a request.

### Output naming consistency

Per-ankh's bake currently aliases `IMPROVEMENT_LIBRARY_1/2/3` to the single `IMPROVEMENT_3D_LIBRARY.png` because the DB uses tiered names. If pinacotheca ever ships per-tier renders, the naming should be predictable (`IMPROVEMENT_3D_LIBRARY_1.png`, `_2.png`, `_3.png`) so per-ankh's manifest can be auto-generated rather than hand-aliased.

If the game doesn't actually use distinct meshes per tier (likely — only the icon/sprite typically changes), this is moot.

## Test cases for pinacotheca to validate against

If the above changes land, per-ankh would re-bake using the same `bake-improvements-test.ts` flow against:

| Asset | What we'd check |
|---|---|
| `IMPROVEMENT_3D_LIBRARY_<FAMILY_*>.png` | Per-family variants render and match in-game screenshots; no plinths |
| `IMPROVEMENT_3D_GRANARY.png` | Unchanged — already correct |
| `IMPROVEMENT_3D_WATERMILL.png` | No splat-shader courtyard artifacts; building visible cleanly |
| `IMPROVEMENT_3D_MARKET.png` | Same — no smoky alphamap artifacts |
| `IMPROVEMENT_3D_KUSHITE_PYRAMID.png` | No square ground plate; just the pyramid geometry |
| `IMPROVEMENT_3D_MAURYA_CAPITAL.png` | Composite renders without alphamap floor; floats above what will become per-ankh's terrain |

## Summary of changes per-ankh wants, ordered by impact

1. **Strip baked plinths** from single-piece improvements (heuristic or config-driven). Unblocks Library, Christian Temple, similar.
2. **Per-family asset variants** keyed by family/culture. Unblocks accurate rendering across all DLC and base cultures.
3. **Skip splat-shader Plane meshes** in prefab walks. Unblocks composite prefabs (wonders, DLC capitals) and prefab-walked improvements with splat children (Watermill, Market).

(1) and (3) are mostly already-described follow-ups in `extracting-3d-buildings.md` — this doc is per-ankh's vote for prioritizing them. (2) is a new finding from the per-ankh map work.

## Contact / iteration

Per-ankh's bake script and runtime composite live at:

- `scripts/bake-improvements-test.ts` — proof-of-concept bake for two improvements
- `src/lib/SpriteMap.svelte` — runtime that composites onto terrain
- `docs/map-beta-future-work.md` — broader map roadmap

Per-ankh can validate any pinacotheca change quickly by re-running the bake script and reloading the dev server. Happy to test variants iteratively.
