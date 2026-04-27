# Code Review — 3D-improvements pipeline rework

**Scope.** Commits `ba93630..d93a5e3` (10 commits, 2026-04-27). This rework extended the 3D pipeline from units-only to also render improvements and nation capitals, replaced the curated `IMPROVEMENT_MESHES`/`COMPOSITE_PREFABS` lists with XML-driven discovery, added the splat-Y plinth-cut and 180° camera flip, and re-synced `CLAUDE.md`/`README.md` plus a few docs.

**Read.** Full diff of `src/pinacotheca/{asset_index,extractor,prefab,renderer,cli}.py`, the new `tests/test_asset_index.py` and the additions in `tests/test_prefab.py`, `CLAUDE.md`, `README.md`, the four docs touched, and `scripts/inspect_*.py`. **Skipped:** `atlas.py`, `gallery.py`, the SvelteKit `web/` tree, and unchanged `tests/test_categories.py`/`tests/test_atlas.py`.

**Verdict.** The rework is in good shape. 165 tests pass (+24 new), the XML-driven discovery is a clear win over the hand-curated tuples it replaces, and the splat-Y plinth + 180° camera flip are well-motivated and gated by safety guards with regression tests for the guards themselves. No correctness bugs were found. The findings below are tidy-up: one broken script, a couple of dead-code patches, a few stale docs claims.

---

## Broken / actionable

### B1. `scripts/inspect_splat_y.py` is broken

The script imports `IMPROVEMENT_MESHES` from `pinacotheca.extractor` (`scripts/inspect_splat_y.py:29`), and that constant was deleted in `86a99ce` along with the curated list. The script raises `ImportError` on first run.

It is still cited as a useful diagnostic in `docs/extracting-3d-buildings.md:167` ("Useful for auditing new entries or DLC content") and referenced from `docs/runtime-composed-cities.md:130` ("See `scripts/inspect_splat_y.py` for the loading boilerplate"). Either:

- Port it to iterate `load_improvement_assets(...)` + `load_capital_assets(...)` from `asset_index.py`, or
- Delete it and remove the doc references.

### B2. `scripts/inspect_barracks.py` is stale

A one-shot debug script for the original plinth heuristic. Its print at `scripts/inspect_barracks.py:150` claims `max_cut_fraction=0.50 cap`, but the production default in `prefab.py:651` is `0.65` (and was already `0.65` in this rework). It still runs, but its output now lies about the algorithm it inspects. The script was a Library/Barracks debug session — recommend deletion rather than maintenance.

---

## Code smells

### S1. `prefab.py` — `vt_offset` / `vn_offset` are dead

`bake_to_obj` (`prefab.py:290`–`360`) initializes `vt_offset = 0` and `vn_offset = 0`, increments them in the per-part loop, then ends with:

```python
_ = vt_offset
_ = vn_offset
```

The trailing `_ =` to suppress lint plus the comment *"Suppress unused-variable warnings; offsets retained for future per-channel index arithmetic if needed"* is the classic "for the future" anti-pattern. Faces are always emitted as `f a/a/a` (vertex index reused for vt/vn slots), which is correct because UnityPy's `MeshHandler` exposes `m_Vertices`/`m_UV0`/`m_Normals` as parallel arrays of equal length — they're guaranteed in lockstep with `v_offset`. Drop both variables.

### S2. `prefab.py` — `_world_y_max` and `_world_y_min` are 90% duplicated

`prefab.py:507`–`547` are two near-identical functions whose only difference is the reduction (`max` vs `min`) and the sentinel (`-inf` vs `+inf`). Collapse to one helper that takes `op=max` and returns the reduced Y, or returns `(min_y, max_y)` so callers can take whichever they need.

### S3. `extractor.py:762` — undocumented clamp on the splat-Y override

```python
splat_y = find_ground_y(lod_kept)
cut_y_override = max(0.0, splat_y) if splat_y is not None else None
```

`find_ground_y` returns the world Y of the prefab's `SplatHeightDefault` plane, and that value can legitimately be negative (the docs explicitly call this out: WALL has its entire mesh below Y=0; `extracting-3d-buildings.md:126`). The `max(0.0, …)` silently re-targets such cases at Y=0, where the safety guards in `strip_plinth_from_obj` will then likely refuse it anyway. Two reasonable resolutions:

- **Drop the clamp.** Let the override flow through; the existing extent + vert-count guards will catch the bad cases. This is the simpler invariant.
- **Keep it but explain.** Add a one-line comment naming the prefab class (or shape) the clamp is meant to protect, so a future reader doesn't have to reverse-engineer the intent.

Either way, the current shape — silent clamp + safety guards downstream — is harder to reason about than either alternative.

### S4. `extractor.py` — three near-identical UnityPy bootstraps

`extract_sprites` (`extractor.py:187`–`272`), `extract_unit_meshes` (`444`–`564`), and `extract_improvement_meshes` (`706`–`819`) each do the same dance:

```python
original_cwd = os.getcwd()
os.chdir(str(game_data))
try:
    env = UnityPy.Environment()
    env.load_file(str(game_data / "resources.assets"))
    ...
finally:
    os.chdir(original_cwd)
```

Not urgent, but a `with unity_env(game_data) as env:` context manager would remove ~30 lines and make the cwd contract explicit (the comment "CRITICAL: Change to Data directory so UnityPy can find .resS files" only appears once at line 186 — the next two callers are the same constraint, undocumented).

### S5. `prefab.py` module docstring is outdated

`prefab.py:2`–`4` opens with *"GameObject/Transform prefab traversal for composite buildings."* Since `86a99ce` collapsed the single-piece + composite extraction paths into one, this module is the **only** render path for all improvements (Library, Granary, capitals, supplemental pyramids — everything). The docstring should say so. Same drift on `prefab.py:553` (in `find_geometry_y_min`'s docstring: *"Used to sanity-check splat-plane Y in composite prefabs"*).

### S6. `asset_index.py` — `load_capital_assets` resolves entries twice

`load_capital_assets` (`asset_index.py:209`–`263`) builds the `variations` dict via `_build_variation_index(variation_entries)`, then iterates `variation_entries` again and re-resolves each entry through `variations.get(z_type)`. Same data, two passes. Cleaner:

```python
for z_type, variation in variations.items():
    if not z_type.startswith("ASSET_VARIATION_CITY_") or not z_type.endswith("_CAPITAL"):
        continue
    ...
```

Behaviorally identical; saves one re-lookup per entry and reads as one intent rather than two.

---

## Documentation drift

These are out-of-sync between the rewritten code and the docs that describe it. None are misleading enough to break user behavior; they just rot the "ground truth" claim of CLAUDE.md.

### D1. `CLAUDE.md:70` — "composites" still listed as an extractor path

Reads *"`extractor.py` — UnityPy extraction (sprites, units, improvements, composites)"*. Composites no longer exist as a distinct path: `extract_composite_meshes` was deleted in `86a99ce` and folded into `extract_improvement_meshes`. Should be `(sprites, units, improvements, capitals)` or just `(sprites, units, improvements)`.

### D2. `CLAUDE.md:78-84` — `docs/runtime-composed-cities.md` missing from listing

The file was added in `974cef9` and is referenced later in the same `CLAUDE.md` at line 264 (*"See `docs/runtime-composed-cities.md`…"*). The directory listing at lines 78–84 should include it.

### D3. `CLAUDE.md:113` — "for composite buildings"

Same drift as S5: the prefab module description says *"Unity GameObject/Transform tree walker for composite buildings"*. It walks single-piece prefabs too now.

### D4. `README.md:156` — tests listing missing `test_asset_index.py`

The file was added in `86a99ce` (456 lines, 9 tests covering the XML chain). Listed in `CLAUDE.md` at line 157, but not in `README.md`'s "Project Structure" tree.

### D5. `README.md:19` — minor phrasing

*"3D rendering of units, improvements, and composite prefabs (DLC capitals, wonders) to 2D images"* — factually still true (DLC capitals like Maurya/Tamil/Yuezhi *are* internally composite prefabs), but the user-facing reader doesn't need that internal distinction. Lower priority than D1–D4 but worth folding into the same sweep.

---

## Notes (positive / neutral)

- The XML-driven discovery is well-tested with **synthetic XML fixtures** under `tmp_path` — no real game files required for CI. Coverage hits the four interesting branches (SingleAsset, aiRandomAssets weight pick, DLC merge, broken-chain skip) plus capital discovery and the missing-XML-dir empty case.
- The plinth-strip safety guards (`max_cut_fraction=0.65` extent cap, `verts_below*2 < total` vert-count cap) have **regression tests for the guards themselves** (`test_strip_plinth_override_rejected_by_extent_guard`, `..._by_vert_count_guard`). This is the right level of defensive testing for a heuristic that needs to be both aggressive and trustworthy.
- The `PREFAB_DECODE_BLACKLIST` for the `Fort` SIGSEGV (`extractor.py:578`–`588`) is well-justified in its docstring; the choice to skip rather than `try`/`except` is correct because SIGSEGV bypasses Python's exception machinery. The "subprocess isolation if it grows past a handful" note is the right deferred-decision call for a one-entry list.
- The `find_root_gameobject` fallback (`prefab.py:113`–`117`) — return the first matching GameObject if no Transform-rooted candidate is found — is a reasonable belt-and-braces and the docstring documents the fallback semantics.
- The `pre_rotation_y_deg` parameter on `bake_to_obj` defaults to `0.0` so existing non-extractor callers see no behavior change; a `det = +1` rotation preserves the winding-flip semantics of the existing code. This is the right shape — opt-in, with a tested default-zero regression case.
