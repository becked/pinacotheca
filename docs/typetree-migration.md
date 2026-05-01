# TypeTree migration plan

## Status

**Not started.** This doc captures a plan worth executing. There's no
deadline; the trigger is "next time a game patch breaks one of our
hand-parsers." When that happens, follow this plan instead of patching
the parser by hand again.

## Motivation

We currently maintain four hand-rolled parsers for Unity MonoBehaviour
binary bodies:

- `pvt_splats.parse_pvt_splat` — `TerrainTexturePVTSplat`
- `pvt_splats.parse_height_splat` — `TerrainHeightSplat` (used to be
  drift-detection only; as of the terrain-3D work, used for real
  rendering too)
- `terrain_clutter_splat.parse_clutter_splat` — `TerrainClutterSplat`
- `clutter_transforms` (the body of `_walk_clutter_transforms`) —
  `ClutterTransforms`

Each one walks the binary byte-by-byte, locked to a specific field
order/types from the decompiled C# at that point in time. End-of-parse
byte-budget assertions catch silent corruption when layouts drift, but
fixing them is mechanical re-derivation of offsets after each game
patch — and it has to be noticed and done.

The standard solution in the Unity-reversing ecosystem is **TypeTree
generation**: a tool reads the game's `Assembly-CSharp.dll` and emits a
JSON description of every MonoBehaviour's serialized field layout,
which UnityPy can consume at decode time. After this lands, a future
patch's only impact is: re-run the generator → commit → done. No
parser code changes unless a field is renamed (in which case grep for
`data["fieldName"]` finds the call sites).

## Approach

Use **AssetRipper.TypeTreeGenerator** (the Mono-build flavor; not
Il2CppDumper, which is for IL2CPP games — Old World is Mono). It's a
.NET CLI tool. UnityPy 1.10+ has TypeTree support via
`env.tpk_extractor` / `obj.read_typetree(typetree_dict)`.

### Integration steps

1. **Vendor the generator binary** under `tools/` (a small .NET tool
   release, ~5 MB) OR document a `dotnet tool install` invocation in
   the new script. Vendored binary is friendlier for first-time setup.

2. **`scripts/regenerate-typetrees.sh`** (and a `.ps1` for Windows):
   - Locate `Assembly-CSharp.dll` (and any DLC assemblies) inside the
     game install (`OldWorld_Data/Managed/`).
   - Run the generator pointing at that folder.
   - Output to `data/typetrees.json` (gzip-compressed if useful).
   - Print a summary: `N classes, M fields total`.

3. **`src/pinacotheca/typetree_loader.py`**:
   - `load_typetrees() -> dict[str, dict]` — reads `data/typetrees.json`
     once per process, caches in module scope.
   - `decode_monobehaviour(obj, class_name) -> dict` — wraps UnityPy's
     `read_typetree` with the loaded JSON, returns a dict of named
     fields.
   - Loud failure if the class name isn't in the JSON or the typetree
     decode fails — same "fail loud" stance as the existing
     byte-budget assertions.

4. **Add a parity test** (`tests/test_typetree_parity.py`):
   - For each of the four MonoBehaviour classes we hand-parse, decode a
     real prefab's instance both ways (hand-parser AND typetree) and
     assert field-by-field equality.
   - Pin one or two known-good asset bundles (small fixtures or use
     game install if present, skip if not — same pattern as
     `tests/test_terrain_index.py::test_real_xml_chain_resolves_28_tiles`).
   - This is the gate for merging the migration: parity proves we can
     swap the call sites without changing behavior.

5. **Per-class migration** (one PR per class, easy to revert):
   1. `TerrainHeightSplat` first — newest hand-parser, most isolated
      callers (only `terrain_height_splat.find_height_splats_in_prefab`
      and the drift-detect call in `pvt_splats.find_pvt_splats_in_prefab`).
   2. `TerrainTexturePVTSplat` — broadly used (capitals, urbans,
      terrain). Touches more call sites.
   3. `TerrainClutterSplat` — used by urban-composite culling.
   4. `ClutterTransforms` — biggest scope, touches the most code; do
      last when confidence is highest.

   Each PR keeps the hand-parser around as a deprecated alias (or
   private helper) so a quick revert is a one-line swap.

6. **Doc + CLAUDE.md update** when migration completes: replace the
   "hand-parse + body-budget assert" pattern descriptions with the
   typetree path. Reference this doc as historical context.

## Per-patch workflow (after migration)

1. Game patches.
2. Run `scripts/regenerate-typetrees.sh`.
3. Run `pytest tests/test_typetree_parity.py` (now without the parity
   gate — just verifies decode succeeds on a known prefab).
4. If a field was renamed, grep finds the call sites; fix and recommit.
5. If a field was removed, the call site fails loudly; decide whether
   to drop it from our parsing or compute a fallback.
6. Commit `data/typetrees.json` + any code adjustments.

Compared to the current per-patch workflow ("notice the body-budget
assert fired, dig into the new C#, recount bytes, update the parser,
add a test"), this is ~10× less work.

## Tradeoffs

- **Adds .NET dependency** for the generator step. Run once per patch,
  not at extraction time. Setup is `dotnet tool install` or vendoring
  a release binary.
- **Generated JSON is committed** to the repo. Probably 1–10 MB
  uncompressed; gzip-friendly. Fine.
- **Slightly slower decode at runtime** — typetree-driven decode walks
  a JSON-defined schema instead of pre-compiled struct unpacks.
  Probably <10% on extraction wall time, dominated by Texture2D decode
  anyway. Worth measuring once.
- **A few MonoBehaviours don't TypeTree cleanly** —
  `ISerializationCallbackReceiver`, `OnAfterDeserialize` reshaping,
  generic type parameters. The parity test catches these. The four we
  care about are vanilla `[SerializeField]` data classes; expected to
  decode cleanly. `ClutterTransforms` is the biggest unknown — it has
  the most complex layout, and the migration order above puts it last
  so we can de-risk on simpler classes first.
- **Existing hand-parsers can stay for one cycle** — TypeTree is
  additive, migration is incremental, no big-bang switch needed.

## Estimated effort

- **Initial setup (steps 1–4)**: ~half a day. Pick the generator,
  wire the script, generate the JSON, register with UnityPy, prove
  parity on `TerrainTexturePVTSplat`.
- **Per-class migration (step 5)**: ~half a day each. The first one is
  ~half a day; subsequent ones are faster as the pattern solidifies.
- **Per patch (after migration)**: ~10 seconds + one commit.

Total upfront: roughly 2 dev-days. Pays back the first time a game
patch would have caused a parser break.

## Why this is worth doing

Three real cases that have already happened and would have been free
under typetrees:

- The PVT splat parser had to be re-derived when `albedo_tint` was
  added (we have the test that catches it now, but writing the test
  was itself effort).
- `ClutterTransforms` field layout is the most fragile; any future
  patch that touches the city/urban clutter layer will likely require
  a re-fit.
- `TerrainHeightSplat` is currently parsed in `pvt_splats.py` for
  drift detection. As of the terrain-3D work it's load-bearing for
  rendering; layout drift would now break a visible feature, not just
  fail an assertion.

The motivation is accumulating. This doc exists so we don't re-discuss
"is typetree the right approach?" the next time a parser breaks — we
just execute the plan above.
