# TypeTree spike — findings

**Status: complete.** Spike validated the migration plan; the migration
itself is now in place (see `typetree-migration.md` and the commit
sequence). The spike code that lived under `scripts/typetree-spike/`
was removed in the cleanup PR — recoverable from git history if needed.

Step-0 validation work referenced in `typetree-migration.md` ("spike
TypeTree decode of ClutterTransforms against a known prefab and confirm
it produces parseable output, *before* committing to the full plan").

## TL;DR

**The migration is viable.** All four target MonoBehaviours decode
cleanly via UnityPy's `read_typetree` against hand-authored schemas, and
every field matches the existing hand-parser output bit-for-bit across
the entire game.

Run on the current Old World install (Unity build 2022 era, Mono):

```
=== ClutterTransforms: 140 instances ===
  ok: 140/140
=== TerrainHeightSplat: 538 instances ===
  ok: 538/538
=== TerrainTexturePVTSplat: 437 instances ===
  ok: 437/437
=== TerrainClutterSplat: 302 instances ===
  ok: 302/302

OVERALL: 1417 passed, 0 failed/diverged
```

ClutterTransforms — the class flagged as the biggest unknown in the
migration plan — handles cleanly despite implementing
`ISerializationCallbackReceiver` (on the nested `Model` and
`ClutterTransform` classes) and despite the deeply nested structure
(`ClutterTransforms → List<Model> → List<ClutterTransform> → Vector3`).

## Confirmed assumptions

1. **Bundles do NOT ship inline typetrees.** Every MonoBehaviour in the
   env has `serialized_type.nodes = None`. Confirms the doc's plan: we
   need an external generator.
2. **UnityPy 1.25's `read_typetree` is sufficient.** Handles every
   shape we use — nested classes, `List<T>`, enums-as-int, `ColorRGBA`,
   `Vector4f`, PPtrs, bool 4-byte alignment, deeply nested structs.
3. **`ISerializationCallbackReceiver` is not a problem.** The interface
   only affects runtime callbacks (`OnAfterDeserialize` is invoked
   *after* decode); the on-disk shape is unchanged. The typetree
   describes the on-disk shape, which is exactly what we decode.
4. **Hand-authoring matches what a generator would emit.** Since
   hand-built schemas work, any correctly implemented generator will
   produce equivalent output. Generator choice is therefore *not*
   load-bearing for the migration.
5. **Adapter layer for parity test is simple.** PascalCase dict keys
   (`fadeOutWhenOccupied`) ↔ snake_case dataclass fields
   (`fade_out_when_occupied`); Vector dicts (`{x,y,z}`) ↔ tuples; PPtr
   dicts (`{m_FileID, m_PathID}`) ↔ our `PPtr(file_id, path_id)`. Total
   adapter code in the spike: ~150 LOC for all four classes. Trivial.

## What we spiked

For each target class, we:

1. Read the C# source (parent class included — `TerrainSplatBase`
   contributes `sortingOffset` to all three splat classes; `ClutterBase`
   contributes nothing serialized).
2. Hand-authored a `TypeTreeNode` tree with field declaration order from
   the C# (Unity serialization rule: public + `[SerializeField]`
   private fields, in declaration order, walked top-down through
   inheritance).
3. Decoded every game instance via UnityPy's `read_typetree`.
4. Decoded the same instance via our existing hand-parser.
5. Asserted field-by-field equivalence.

The fact that this all-instances run produced zero divergences across
1417 objects is strong validation: the schemas are correct *and* the
decoder is reliable across the full distribution of real game data
(sparse capitals, urban tiles, every biome, every height, every
improvement, every DLC variant).

## What's deferred to the plan session

These were out of scope for the spike (toolchain choices, not
validation):

1. **Pick a generator.** Candidates surveyed but not selected:
   - **AssetRipper.TypeTreeGenerator** — referenced in the original
     plan; haven't confirmed maintenance status or `dotnet tool install`
     availability.
   - **AssetsTools.NET (nesrak1)** — well-maintained, can dump typetrees
     via a small C# script; could be vendored or wrapped.
   - **AssetRipper proper (CLI)** — heavyweight but proven.
   - **Build our own** — Mono.Cecil reads the assembly's `[SerializeField]`
     declarations directly; we know the rules and the format. ~200 LOC
     of C# would do it. Most flexible, most maintenance.
2. **JSON storage format.** The generator's output format may not match
   UnityPy's `TypeTreeNode` shape directly; we may need a small
   converter at load time (cheap — once per process).
3. **DLC handling.** Old World DLC ships data XML and assets but (we
   believe) no new MonoBehaviour classes in separate assemblies. To
   verify: list the DLLs in `Managed/` and grep for any other
   `Assembly-CSharp*.dll`.
4. **Whether to keep hand-parsers as fallback.** Original plan has them
   stay as deprecated aliases for one cycle. The parity test makes this
   easy and reversible. Fine.

## Open question worth discussing in the plan session

The original migration doc proposes one PR per class with the
hand-parser kept as a fallback. Given the spike result — all four
classes work cleanly — there's an argument for landing the toolchain
(generator + loader + adapter) in one PR and the four call-site swaps
each in their own follow-up PR. Roughly:

- PR 1: vendor/install generator, write `regenerate-typetrees.{sh,ps1}`,
  ship `data/typetrees.json`, write `typetree_loader.py` with a small
  format converter, write the parity test harness covering all four
  classes (this is where the spike-quality validation lands as a
  permanent test).
- PRs 2-5: per class, swap call sites; hand-parser stays as deprecated
  alias for one cycle then gets deleted.

Worth deciding which framing to use.

## Spike artifacts

- `scripts/typetree-spike/clutter_typetree.py` — hand-authored typetree
  for ClutterTransforms + helper builders.
- `scripts/typetree-spike/splat_typetrees.py` — hand-authored typetrees
  for the three Terrain*Splat classes.
- `scripts/typetree-spike/run_spike.py` — single-instance ClutterTransforms
  parity check (kept for narration).
- `scripts/typetree-spike/run_all_spike.py` — full-env parity sweep over
  all 4 classes (the load-bearing result).

These are off-tree and should NOT be moved into `src/` as-is — they're
proof-of-concept. The eventual migration replaces them with proper
typetree generation + a clean loader API.
