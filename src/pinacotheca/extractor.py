"""
Sprite extraction from Unity asset bundles.

Uses UnityPy to extract sprites directly from Old World's game files.
"""

import gc
import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from pinacotheca.categories import CATEGORIES, categorize

if TYPE_CHECKING:
    from UnityPy import Environment

# Platform-specific game data paths
GAME_DATA_MAC = (
    Path.home()
    / "Library/Application Support/Steam/steamapps/common/Old World/OldWorld.app/Contents/Resources/Data"
)
GAME_DATA_WIN = Path("C:/Program Files (x86)/Steam/steamapps/common/Old World/OldWorld_Data")


def find_game_data() -> Path | None:
    """
    Auto-detect the game data directory.

    Returns:
        Path to the game's Data directory, or None if not found
    """
    if GAME_DATA_MAC.exists():
        return GAME_DATA_MAC
    if GAME_DATA_WIN.exists():
        return GAME_DATA_WIN
    return None


def extract_sprites(
    game_data: Path | None = None,
    output_dir: Path | None = None,
    *,
    verbose: bool = True,
) -> dict[str, int]:
    """
    Extract all sprites from Old World assets.

    Args:
        game_data: Path to game's Data directory (auto-detected if None)
        output_dir: Where to save extracted sprites (defaults to ./extracted)
        verbose: Print progress messages

    Returns:
        Dict mapping category names to count of sprites extracted

    Raises:
        FileNotFoundError: If game data directory not found
        ImportError: If UnityPy is not installed
    """
    try:
        import UnityPy
    except ImportError:
        print("ERROR: UnityPy not installed", file=sys.stderr)
        print("Install with: pip install UnityPy Pillow", file=sys.stderr)
        raise

    # Resolve paths
    if game_data is None:
        game_data = find_game_data()
    if game_data is None or not game_data.exists():
        raise FileNotFoundError(
            f"Could not find Old World game data!\n"
            f"Expected locations:\n"
            f"  macOS: {GAME_DATA_MAC}\n"
            f"  Windows: {GAME_DATA_WIN}"
        )

    if output_dir is None:
        output_dir = Path.cwd() / "extracted"

    if verbose:
        print("=" * 60)
        print("Old World Sprite Extractor")
        print("=" * 60)
        print(f"\nGame data: {game_data}")
        print(f"Output: {output_dir}")

    # Create output directories
    sprites_dir = output_dir / "sprites"
    for cat in CATEGORIES:
        (sprites_dir / cat).mkdir(parents=True, exist_ok=True)

    # Clean up stale category folders (from previous extractions with different categories)
    if sprites_dir.exists():
        valid_categories = set(CATEGORIES.keys())
        for item in sprites_dir.iterdir():
            if item.is_dir() and item.name not in valid_categories:
                if verbose:
                    print(f"Removing stale category folder: {item.name}/")
                shutil.rmtree(item)

    # CRITICAL: Change to Data directory so UnityPy can find .resS files
    original_cwd = os.getcwd()
    os.chdir(str(game_data))

    try:
        if verbose:
            print("\nLoading asset index...")

        env: Environment = UnityPy.Environment()
        env.load_file(str(game_data / "resources.assets"))

        # Filter to just Sprite objects
        sprites = [obj for obj in env.objects if obj.type.name == "Sprite"]
        total = len(sprites)

        if verbose:
            print(f"Found {total:,} sprites\n")
            print("Extracting sprites...")

        counts: dict[str, int] = dict.fromkeys(CATEGORIES, 0)
        errors = 0

        for i, obj in enumerate(sprites):
            try:
                data = obj.read()
                name = getattr(data, "m_Name", "")

                if name:
                    img = data.image
                    if img:
                        cat = categorize(name)

                        # Large uncategorized images are backgrounds
                        if cat == "other" and img.width >= 1024:
                            cat = "backgrounds"

                        out_path = sprites_dir / cat / f"{name}.png"

                        if not out_path.exists():
                            img.save(out_path)
                            counts[cat] += 1

                        del img
                del data

            except Exception:
                errors += 1

            # Progress and memory management
            if verbose and (i + 1) % 500 == 0:
                gc.collect()
                extracted = sum(counts.values())
                print(f"  Progress: {i + 1:,}/{total:,} | Extracted: {extracted:,}")

        # Summary
        total_extracted = sum(counts.values())

        if verbose:
            print("\n" + "=" * 60)
            print("EXTRACTION COMPLETE")
            print("=" * 60)
            print(f"Total sprites extracted: {total_extracted:,}")
            print(f"Errors: {errors:,}")
            print("\nBy category:")
            for cat, count in sorted(counts.items(), key=lambda x: -x[1]):
                if count > 0:
                    print(f"  {cat}: {count:,}")
            print(f"\nOutput saved to: {sprites_dir}")

        return counts

    finally:
        os.chdir(original_cwd)
