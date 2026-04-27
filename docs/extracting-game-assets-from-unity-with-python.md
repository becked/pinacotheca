# Extracting Game Assets from Unity with Python

I wanted to build a browsable gallery of every sprite in [Old World](https://www.mohawkgames.com/oldworld/), a 4X strategy game by Mohawk Games. The game has thousands of them — portraits, unit icons, crests, terrain tiles, resource icons — all packed inside Unity asset bundles. Tools like [AssetRipper](https://github.com/AssetRipper/AssetRipper) can extract everything from a Unity game, but I wanted something more targeted: a Python script that pulls just the sprites, categorizes them automatically, and outputs organized PNGs ready for a web gallery.

The result is [Pinacotheca](https://github.com/becked/pinacotheca), a small Python package that extracts and catalogs 4,000+ sprites from Old World's game files. This post covers how it works.

## How Unity stores assets

Before diving into code, it helps to understand what we're working with. Unity games ship their assets in a few key files inside the game's `Data` directory:

- **`.assets` files** — Serialized bundles containing metadata for textures, sprites, meshes, audio, and other game objects. The main one for Old World is `resources.assets`.
- **`.resS` files** — Raw resource data (the actual pixel data for textures) referenced by the `.assets` files. These sit alongside the `.assets` files in the same directory.
- **Sprite objects** — A Sprite in Unity is a 2D image, often a sub-region of a larger texture atlas. Each Sprite has a name, dimensions, and a reference to its source texture.

## Setting up

The heavy lifting is done by [UnityPy](https://github.com/K0lb3/UnityPy), a Python library for reading Unity asset files. Combined with [Pillow](https://pillow.readthedocs.io/) for image handling, the dependencies are minimal:

```toml
dependencies = [
    "UnityPy>=1.10.0",
    "Pillow>=10.0.0",
]
```

The first step is finding the game's `Data` directory. Old World installs to different locations depending on platform:

```python
from pathlib import Path

GAME_DATA_MAC = (
    Path.home()
    / "Library/Application Support/Steam/steamapps/common"
    / "Old World/OldWorld.app/Contents/Resources/Data"
)
GAME_DATA_WIN = Path(
    "C:/Program Files (x86)/Steam/steamapps/common/Old World/OldWorld_Data"
)

def find_game_data() -> Path | None:
    """Auto-detect the game data directory."""
    if GAME_DATA_MAC.exists():
        return GAME_DATA_MAC
    if GAME_DATA_WIN.exists():
        return GAME_DATA_WIN
    return None
```

Nothing clever here — just check the default Steam paths and return whichever exists. You could extend this with registry lookups on Windows or `libraryfolders.vdf` parsing for custom Steam library locations, but the simple version covers 90% of setups.

## Loading and filtering sprites

With the game data directory located, loading sprites is straightforward. Passing the full path to `UnityPy.load()` is important — UnityPy uses the parent directory to resolve `.resS` resource files where the actual pixel data lives. If it can't find them, sprites come back blank.

```python
import UnityPy

env = UnityPy.load(str(game_data / "resources.assets"))

# Filter to just Sprite objects
sprites = [obj for obj in env.objects if obj.type.name == "Sprite"]
print(f"Found {len(sprites):,} sprites")  # ~4,200 for Old World
```

`env.objects` contains *every* object in the asset file — meshes, textures, audio clips, shaders, materials, everything. Filtering by `type.name == "Sprite"` narrows it down to the 2D images we want.

Each sprite object can be read to get its name and image:

```python
data = obj.read()
name = data.m_Name    # e.g., "UNIT_ARCHER", "ROME_MALE_01"
img = data.image      # PIL.Image.Image
```

UnityPy handles the hard work of finding the sprite's source texture, extracting the correct sub-region (sprites are often packed into atlas sheets), and returning a properly cropped PIL Image.

## Categorizing 4,000 sprites

Old World names its sprites with consistent prefixes: `UNIT_ARCHER`, `TECH_IRON_WORKING`, `CREST_NATION_ROME`. This makes regex-based categorization surprisingly effective.

The system is an ordered dictionary mapping category names to regex patterns:

```python
import re
from typing import Final

CATEGORIES: Final[dict[str, str]] = {
    "portraits": r"^(ASSYRIA|BABYLONIA|CARTHAGE|EGYPT|GREECE|ROME|...)_(FEMALE|MALE)_",
    "units": r"^UNIT_(ARCHER|AXEMAN|BALLISTA|CATAPHRACT|CHARIOT|...)",
    "unit_actions": r"^UNIT_(ACTION_|ATTACKED|CAPTURED|DAMAGED|DEAD|...)",
    "crests": r"^CREST_",
    "improvements": r"^IMPROVEMENT_",
    "resources": r"^(RESOURCE_|GOOD_)",
    "techs": r"^TECH_",
    # ... ~40 categories total ...
    "other": r".*",  # catch-all
}
```

Order matters. The first matching pattern wins, so more specific patterns must come before general ones. For example, `MILITARY_DEFEAT` should be categorized as a background, not a unit effect — so the `backgrounds` pattern (`r"^(PORTRAIT_BACKGROUND|MILITARY_DEFEAT)"`) must precede the `unit_effects` pattern (`r"^(EFFECTUNIT_|MILITARY_)"`).

Pre-compiling the patterns at module load avoids recompiling them for each of the 4,000+ sprites:

```python
_COMPILED_PATTERNS: dict[str, re.Pattern[str]] = {
    cat: re.compile(pattern, re.IGNORECASE)
    for cat, pattern in CATEGORIES.items()
}

def categorize(name: str) -> str:
    """Return the category for a sprite name. First match wins."""
    for cat, pattern in _COMPILED_PATTERNS.items():
        if pattern.match(name):
            return cat
    return "other"
```

This system has held up well — 95 unit tests validate the categorization, and adding a new category is just a matter of inserting a pattern in the right position in the dict.

## Memory management at scale

The naive approach — iterate over all sprites, read each one, save the image — works fine for a few hundred sprites. At 4,000+, it runs the process into multi-gigabyte memory usage and eventually crashes.

The problem is that each `obj.read()` call loads texture data into memory, and Python's garbage collector doesn't always reclaim it promptly. Sprite images reference large underlying texture atlases, so even though the cropped sprite might be 64x64 pixels, the full texture it was sliced from could be 2048x2048.

The fix is explicit cleanup:

```python
counts: dict[str, int] = {}
errors = 0

for i, obj in enumerate(sprites):
    try:
        data = obj.read()
        name = data.m_Name

        if name:
            img = data.image
            if img:
                cat = categorize(name)
                out_path = sprites_dir / cat / f"{name}.png"

                if not out_path.exists():
                    img.save(out_path)
                    counts[cat] = counts.get(cat, 0) + 1

                del img
            del data

    except Exception:
        errors += 1

    # Force garbage collection periodically
    if (i + 1) % 500 == 0:
        gc.collect()
        extracted = sum(counts.values())
        print(f"  Progress: {i + 1:,}/{len(sprites):,} | Extracted: {extracted:,}")
```

Three things make this work:

1. **`del img` and `del data`** — Explicitly drop references to the image and read data as soon as we're done with them. Without this, Python holds references until the loop variable is reassigned on the next iteration, which means two sprites' worth of texture data in memory at once.

2. **`gc.collect()` every 500 sprites** — Forces the garbage collector to reclaim memory from circular references and other objects that reference counting alone can't free. Every 500 is a sweet spot: frequent enough to keep memory stable, infrequent enough to not tank performance.

3. **Skip existing files** — `if not out_path.exists()` means re-running the extractor doesn't re-process sprites that have already been saved. This also means we can skip loading the image entirely for duplicates, though the current implementation still reads the data to get the name.

With these three techniques, memory usage stays flat at around 500MB throughout the extraction — well within reason for a tool processing gigabytes of game assets.

## Putting it all together

The full extraction flow looks like this:

1. **Find the game** — Auto-detect the platform-specific Steam installation path
2. **Create output directories** — One subdirectory per category under `extracted/sprites/`
3. **Clean stale categories** — If you've renamed or removed categories since the last run, delete the orphaned directories
4. **Load and filter** — Open `resources.assets`, filter to Sprite objects
5. **Extract loop** — For each sprite: read, categorize, save as PNG, clean up memory

The final output is a clean directory tree:

```
extracted/
└── sprites/
    ├── portraits/     # 600+ character portraits
    ├── units/         # Military unit icons
    ├── crests/        # Nation and family emblems
    ├── techs/         # Technology icons
    ├── resources/     # Resource and goods icons
    ├── terrains/      # Terrain tiles
    └── ...            # ~40 categories total
```

Each category directory contains PNGs named after the original sprite: `UNIT_ARCHER.png`, `TECH_IRON_WORKING.png`, `CREST_NATION_ROME.png`. No metadata to track, no database to query — just files on disk, organized by what they are.

## What's next

This gets us a directory full of organized PNGs, but raw files aren't much fun to browse. In the next post, I'll cover building an interactive web gallery with SvelteKit — including fuzzy search, dimension filtering, and URL-driven state that makes every view shareable. And after that, a deep dive into headless 3D rendering: turning Unity meshes into 2D sprite images using Python and OpenGL, no game engine required.
