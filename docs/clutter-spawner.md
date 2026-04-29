# ClutterSpawner — deferred procedural-clutter support

## Symptom

`RESOURCE_3D_SALT_*.png` shows only the static `Salt_Rock` mesh — a
single grey rocky lump. In-game, salt tiles also display a scatter of
salt deposit chunks around the rock; those chunks are missing from
our render.

## Cause

The Salt prefab (`Prefabs/Resource/Salt`) has the structure:

```
Salt
├── Salt_Deposit_Chunks   [Transform + MonoBehaviour: ClutterSpawner]
├── ScrubSplatPVT         [Quad / SplatTextureDefaultPVT — dropped by drop_splat_meshes]
└── SaltRock              [Salt_Rock mesh — the only thing we currently render]
```

`Salt_Deposit_Chunks` carries a **`ClutterSpawner`** MonoBehaviour. This
is a separate composition system from the `ClutterTransforms` we
already support (see `src/pinacotheca/clutter_transforms.py` and
`docs/runtime-composed-cities.md`):

- `ClutterTransforms` — explicit list of `(model, instance_TRS)` pairs.
  Static, deterministic. Used by sparse capitals + most static
  resource decorations (Stone, Citrus, Incense, Ebony).
- `ClutterSpawner` — *procedural* runtime spawner. The serialized
  payload defines `numInstances`, `gridBounds`, `minPosition`,
  `maxPosition`, `minRotation`, `maxRotation`, `minScale`, `maxScale`,
  `randomSeed`, etc. (see
  `decompiled/Assembly-CSharp/ClutterSpawner.cs`). Instances are
  generated at runtime from the seed.

UnityPy's typetree for ClutterSpawner is incomplete (the body is
~316 bytes; UnityPy's parser only consumes ~32). Adding support means
hand-parsing the binary layout against the C# class fields, and then
implementing a procedural spawner that reproduces the runtime's
seeded RNG.

## Status

Deferred. The Salt issue was identified during the alpha-cutout +
body-axis-Y + multi-rig-split round; ClutterSpawner support is a
substantial new feature comparable to the existing ClutterTransforms
implementation and warrants its own plan.

## Other resources likely affected

Any resource prefab whose root has a child named `*_Deposit_Chunks`,
`*_Spawner`, or similar. A follow-up survey can grep
`grep -l "ClutterSpawner" decompiled/Assembly-CSharp/*.cs` and probe
each resource prefab's MonoBehaviour list for the script class.

## Implementation reference

When picking this up:

1. Hand-parse the `ClutterSpawner` MonoBehaviour body using the field
   layout from `ClutterSpawner.cs` (the `Model` nested class is the
   bulk of the payload — see field list at lines 11–84).
2. Reproduce Unity's `Random` with the saved `randomSeed` (Unity uses
   `System.Random` for non-deterministic Unity APIs; for deterministic
   seeded behavior the spawner likely uses `UnityEngine.Random` with
   `Random.InitState(seed)` — verify against the runtime).
3. Generate `numInstances` `(position, rotation, scale)` tuples within
   `gridBounds` using `minPosition…maxPosition`, `minRotation…
   maxRotation`, `minScale…maxScale`.
4. Emit one `PrefabPart` per instance, applying the parent prefab's
   root TRS, the spawner GO's local TRS, and the per-instance TRS.

The output integrates into `extract_improvement_meshes` the same way
ClutterTransforms parts do — concatenated into `combined` before
`bake_to_obj`.
