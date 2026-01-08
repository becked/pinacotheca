#!/usr/bin/env python3
"""
Quick ad-hoc script to list 2D assets from Old World game data.

Usage:
    python scripts/list_2d_assets.py [--type TYPE] [--filter PATTERN]

Examples:
    python scripts/list_2d_assets.py                     # List all 2D asset types
    python scripts/list_2d_assets.py --type Sprite       # List all sprites
    python scripts/list_2d_assets.py --type Texture2D --filter chariot  # Filter textures
"""

import argparse
import os
import re
import sys
from collections import Counter
from pathlib import Path

# Game data paths
GAME_DATA_MAC = (
    Path.home()
    / "Library/Application Support/Steam/steamapps/common/Old World/OldWorld.app/Contents/Resources/Data"
)
GAME_DATA_WIN = Path("C:/Program Files (x86)/Steam/steamapps/common/Old World/OldWorld_Data")


def find_game_data() -> Path | None:
    """Auto-detect the game data directory."""
    if GAME_DATA_MAC.exists():
        return GAME_DATA_MAC
    if GAME_DATA_WIN.exists():
        return GAME_DATA_WIN
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="List 2D assets from Old World")
    parser.add_argument(
        "--type",
        "-t",
        choices=["Sprite", "Texture2D", "all"],
        default="all",
        help="Asset type to list (default: all = show summary)",
    )
    parser.add_argument(
        "--filter",
        "-f",
        type=str,
        default=None,
        help="Filter by name pattern (case-insensitive regex)",
    )
    parser.add_argument("--limit", "-n", type=int, default=None, help="Limit output to N results")
    args = parser.parse_args()

    try:
        import UnityPy
    except ImportError:
        print("ERROR: UnityPy not installed", file=sys.stderr)
        print("Install with: pip install UnityPy", file=sys.stderr)
        sys.exit(1)

    game_data = find_game_data()
    if not game_data:
        print("ERROR: Could not find Old World game data", file=sys.stderr)
        sys.exit(1)

    print(f"Game data: {game_data}\n")

    # Change to game data dir for UnityPy to find .resS files
    original_cwd = os.getcwd()
    os.chdir(str(game_data))

    try:
        print("Loading assets...")
        env = UnityPy.Environment()
        env.load_file(str(game_data / "resources.assets"))

        # Collect 2D asset types
        type_counts: Counter[str] = Counter()
        assets: list[tuple[str, str, int, int]] = []  # (type, name, width, height)

        for obj in env.objects:
            type_name = obj.type.name

            # Only process 2D asset types
            if type_name not in ("Sprite", "Texture2D"):
                continue

            type_counts[type_name] += 1

            # If filtering by type, read details
            if args.type != "all" and type_name == args.type:
                data = obj.read()
                name = getattr(data, "m_Name", "<unnamed>")

                # Get dimensions
                if type_name == "Sprite":
                    img = data.image
                    width, height = (img.width, img.height) if img else (0, 0)
                else:  # Texture2D
                    width = getattr(data, "m_Width", 0)
                    height = getattr(data, "m_Height", 0)

                # Apply filter
                if args.filter and not re.search(args.filter, name, re.IGNORECASE):
                    continue

                assets.append((type_name, name, width, height))

        # Output
        if args.type == "all":
            print("\n2D Asset Summary:")
            print("-" * 40)
            for type_name, count in sorted(type_counts.items()):
                print(f"  {type_name}: {count:,}")
            print(f"\nTotal: {sum(type_counts.values()):,}")
        else:
            # Sort by name
            assets.sort(key=lambda x: x[1].lower())

            if args.limit:
                assets = assets[: args.limit]

            print(f"\n{args.type} assets ({len(assets):,} found):")
            print("-" * 60)
            for _type_name, name, width, height in assets:
                print(f"  {name:<50} {width}x{height}")

    finally:
        os.chdir(original_cwd)


if __name__ == "__main__":
    main()
