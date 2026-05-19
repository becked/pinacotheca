# Mod Extraction

Pinacotheca scans the user's local Old World mods directory and extracts
visual assets from each installed mod's Unity AssetBundles, alongside
the base-game extraction. Outputs land under
`extracted/sprites/mods/<slug>/<sub>/<filename>.png`. The SvelteKit
gallery surfaces them in a dedicated **Mods** section with per-sprite
attribution.

## What gets extracted

`src/pinacotheca/mod_scanner.py` walks the mods directory:

- **macOS**: `~/Library/Application Support/OldWorld/Mods/`
- **Windows**: `~/Documents/My Games/OldWorld/Mods/`

For each mod with an `Assets/` directory it parses `ModInfo.xml` (display
name, author, version, description) and inspects each bundle's class
counts to classify it:

- **3D bundle** — has `Mesh` objects. Rendered via the existing prefab
  walker (`prefab.walk_prefab` already supports `SkinnedMeshRenderer`
  leaves for rigged unit meshes). The walker is XML-driven when the mod
  ships `Infos/asset-*.xml` (preferred), or falls back to a bundle scan
  for prefabs with no parent transform.
- **2D bundle** — has `Sprite` or `Texture2D` objects. Iterates and
  saves each as PNG.
- **Gameplay-only bundle** — has only `MonoBehaviour`/`AssetBundle`
  headers. Skipped.

Cross-platform note: AssetBundles are platform-tagged at build time but
the binary container is shared; UnityPy reads either Windows- or macOS-
targeted bundles, and `texture2ddecoder` (already a dep) handles all
common GPU texture formats. The only platform-dependent piece of a mod
is its C# DLL, which we don't need.

### 2D Sprite fallback

A handful of mods ship `Sprite` metadata that triggers a UnityPy
crop-rect bug, producing fully-transparent PNGs. `_extract_2d_bundle`
detects empty sprite output (`Image.getbbox() is None`) and falls back
to the matching `Texture2D` by name. Greek Dynasties' resource bundle
is the canonical example — 9 sprites would otherwise extract blank.

## Output layout

```
extracted/sprites/mods/
├── byzantine-empire/
│   ├── mod.json                 ← attribution + ModInfo metadata
│   └── sprites/                 ← 2D
│       └── *.png
├── dynamic-unit/
│   ├── mod.json
│   └── sprites/                 ← 2D
│       └── *.png
├── nation-specific-graphics-units/
│   ├── mod.json
│   └── units/                   ← 3D unit renders (FRONT/BACK)
│       └── UNIT_3D_<NATION>_ELITE_SWORDSMAN_<VIEW>.{png,json}
└── ...
```

Each `.png` 3D render gets a JSON sidecar at the same stem (same schema
as base-game 3D outputs, see `render_metadata.py`).

## Front/back rendering for 3D mod units

3D mod meshes don't share a canonical authored facing direction —
Shirotora Kenshin's NSG meshes for Aksum/Greece/Hittites/Nubia face -Z
(toward our camera after the standard 180° flip), while the other six
nations face +Z. Rather than detect facing direction per mesh, we
render every 3D mod prefab in **both orientations** (`_FRONT` + `_BACK`
suffixes).

For prefabs that authored facing +Z, the suffix-to-rotation mapping is
swapped (via `_BACK_AUTHORED_PREFABS` in `mod_extractor.py`) so that
`_FRONT` is always the soldier's face, regardless of how the mesh was
authored.

## Attribution

Each mod sprite carries an `authors: string[]` field in the manifest.
The TS-side `generate-manifest.ts` resolves it from the mod's
`mod.json` `attribution` block, written by Python's
`_resolved_attribution` function in `mod_extractor.py`.

### The `_MOD_ATTRIBUTION` table

The `<author>` field in ModInfo names the primary author, but mods
routinely bundle work from collaborators that ModInfo doesn't expose as
structured data:

- Sometimes mentioned only in the free-text description (Dynamic Unit
  thanks "And" for icons; NSG credits the same in its Credits block).
- Sometimes communicated out-of-band (Maniac's Greek Dynasties mod
  ships NSG's mesh set without crediting it inline).

Free-text parsing of descriptions is too brittle, so `_MOD_ATTRIBUTION`
in `src/pinacotheca/mod_extractor.py` is an explicit table:

```python
_MOD_ATTRIBUTION: dict[str, dict[str, Any]] = {
    "dynamic-unit": {
        "default": ["Harry", "And"],
    },
    "nation-specific-graphics-units": {
        "default": ["Shirotora Kenshin", "And", "Harry"],
    },
    "the-greek-dynasties": {
        "default": ["Maniac"],
        "overrides": [
            {"pattern": r"^UNIT_3D_", "authors": ["Maniac", "Shirotora Kenshin"]},
            {"pattern": r"^RESOURCE_", "authors": ["Maniac", "Revan"]},
        ],
    },
}
```

`default` is the fallback for every sprite; `overrides` apply when a
sprite's basename matches the pattern (first match wins, evaluated in
list order).

Each entry resolves to `{"default": [...], "overrides": [...]}` and is
written into the mod's `mod.json` so the TS manifest gen can stamp
per-sprite authors without re-parsing the source. The TS-side mirror
`resolveAuthors()` in `web/scripts/generate-manifest.ts` evaluates the
same logic.

### Gallery UI

- **SpriteCard** (search results, mod browse view): renders a subtle
  italic "by X & Y" line under each mod sprite's name.
- **Lightbox**: shows "from `<Mod Name>` · by X & Y" in the metadata
  area for mod sprites.

## Artist opt-out — `EXCLUDED_AUTHORS`

Some creators ask that their work not appear in the deployed
pinacotheca gallery. `EXCLUDED_AUTHORS` in `mod_extractor.py`:

```python
EXCLUDED_AUTHORS: frozenset[str] = frozenset({"Shirotora Kenshin"})
```

The mechanism follows the credits, not file paths — so any mod that
bundles work by an excluded author has those files filtered out
automatically as long as `_MOD_ATTRIBUTION` credits them.

### How it works

1. **Extraction proceeds normally.** All sprites get written to disk,
   including those by excluded authors. The local user retains every
   file the mod offers — useful for per-ankh, Finder browsing, or local
   inspection.

2. **At sidecar-write time**, `compute_excluded_mod_globs(output_dir)`
   walks every mod's `mod.json`, resolves each `.png` file's authors
   against the attribution table, and emits literal-path globs for
   files whose authors intersect `EXCLUDED_AUTHORS`. Both the `.png`
   and its `.json` render-metadata sidecar are added.

3. **The gallery-filter sidecar** (`extracted/.gallery-filter.json`)
   merges these dynamic globs with the static `GALLERY_EXCLUDE_GLOBS`
   list. The downstream consumers are unchanged:
   - SvelteKit manifest generation (`npm run manifest`) skips matching
     paths — they don't appear in the gallery's Mods section.
   - `pinacotheca-deploy` reads the same merged list from the sidecar
     and `--exclude`s matching paths from the `rsync` to the gh-pages
     branch.

4. **Mods with zero remaining sprites are dropped from the manifest's
   `mods[]` automatically** — `scanMods` in `generate-manifest.ts` only
   appends an entry when `count > 0`. NSG (entirely Shirotora
   Kenshin's work) disappears from the Mods section; Greek Dynasties
   stays with its 9 RESOURCE_* icons (2 UNIT_3D_* removed).

### Reversibility

If an author later changes their stance:

1. Remove their name from `EXCLUDED_AUTHORS`.
2. Re-run `pinacotheca-mods` (or any command that writes the sidecar
   — `pinacotheca`, `pinacotheca-web-build`).

The sidecar is rewritten with the artist's globs removed; the next
manifest build picks them up and the Mods section repopulates.

### Pattern contract

The sidecar's exclude globs share the same pattern contract as
`GALLERY_EXCLUDE_GLOBS`:

- Only `*` wildcards (no `?`, no `[...]`, no `**`).
- `*` does not cross `/`.
- Validated by `_validate_patterns()` at write time.

Computed mod-author globs use literal file paths (no wildcards), which
trivially satisfy the contract.

## CLI

```bash
# Full extraction including mods (default)
pinacotheca

# Skip mods
pinacotheca --no-mods

# Re-extract mods only (faster than the full pipeline)
pinacotheca-mods

# Override the mods directory
pinacotheca-mods --mods-dir ~/path/to/Mods
```

All four entry points (`pinacotheca`, `pinacotheca-mods`,
`pinacotheca-web-build`, `pinacotheca-deploy`) read the merged glob
list from the sidecar, so artist exclusions apply automatically
wherever the filter is consulted.

## Files

- `src/pinacotheca/mod_scanner.py` — discovery, ModInfo parsing,
  bundle classification.
- `src/pinacotheca/mod_extractor.py` — extraction, attribution table,
  `EXCLUDED_AUTHORS`, `compute_excluded_mod_globs()`.
- `src/pinacotheca/gallery_filter.py` — pattern contract,
  `write_filter_sidecar(extra_globs=...)`.
- `web/scripts/generate-manifest.ts` — TS-side scanMods + author
  resolution + per-sprite stamping.
- `web/src/lib/components/ModCard.svelte`,
  `web/src/lib/components/SpriteCard.svelte`,
  `web/src/routes/+page.svelte` — UI surfaces.
