#!/usr/bin/env python3
"""Preview which sprites would be excluded by .exclude-patterns."""

import os
from pathlib import Path

from pinacotheca.extractor import load_exclusion_pattern, find_game_data


def main() -> None:
    pattern = load_exclusion_pattern()
    if not pattern:
        print("No .exclude-patterns file found (or it's empty)")
        return

    print(f"Pattern: {pattern.pattern}\n")

    game_data = find_game_data()
    if not game_data:
        print("Could not find game data")
        return

    os.chdir(str(game_data))

    import UnityPy

    env = UnityPy.load(str(game_data / "resources.assets"))

    matches: list[str] = []
    for obj in env.objects:
        if obj.type.name == "Sprite":
            data = obj.read()
            name = getattr(data, "m_Name", "")
            if name and pattern.search(name):
                matches.append(name)

    print(f"Would exclude {len(matches)} sprites:\n")
    for name in sorted(set(matches)):  # dedupe
        print(f"  {name}")


if __name__ == "__main__":
    main()
