"""Find textures associated with selected building meshes.

For each target mesh, list candidate Texture2D names from the assets
that share substrings with the mesh name. Helps figure out the naming
convention buildings use vs the unit `_Diffuse` convention.
"""

from __future__ import annotations

import os
import re

import UnityPy

from pinacotheca.extractor import find_game_data

# A handful of buildings to probe — covers religious, civic, military, wonder,
# DLC-flavored, and a non-LOD-suffixed name.
TARGETS = [
    "Library_LOD0",
    "Barracks_LOD0",
    "Granary_LOD0",
    "ChristianTemple_LOD0",
    "Hunting_Shrine_LOD0",
    "Watermill_LOD0",
    "lumbermill_geo_LOD0",
    "Maurya_Capital",
    "Tamil_Capital",
    "AksumCapitol",
    "Kushite Pyramid",
    "Hanging_Garden",
    "TheaterPompey",
    "Academy",
    "Market",
]


def normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def main() -> None:
    game_data = find_game_data()
    if game_data is None:
        raise SystemExit("Game data not found")

    os.chdir(str(game_data))
    env = UnityPy.Environment()
    env.load_file(str(game_data / "resources.assets"))

    textures: list[tuple[str, int, int]] = []
    for obj in env.objects:
        if obj.type.name != "Texture2D":
            continue
        try:
            data = obj.read()
            name = getattr(data, "m_Name", "") or ""
            if not name:
                continue
            w = getattr(data, "m_Width", 0)
            h = getattr(data, "m_Height", 0)
            textures.append((name, w, h))
        except Exception:
            pass

    print(f"Loaded {len(textures)} textures.\n")

    for target in TARGETS:
        # Strip _LOD0/1/2 suffix; treat as base
        base = re.sub(r"_LOD\d+$", "", target, flags=re.IGNORECASE)
        base_norm = normalize(base)

        # Score each texture by (a) substring containment and (b) whether
        # it has _Diffuse / _Albedo / _BaseColor suffix.
        candidates: list[tuple[str, int, int, int]] = []
        for name, w, h in textures:
            n = normalize(name)
            score = 0
            if base_norm and base_norm in n:
                score += 10
            if n in base_norm and len(n) >= 4:
                score += 5
            # Token overlap
            for tok in re.findall(r"[A-Za-z]+", base):
                if len(tok) >= 4 and tok.lower() in name.lower():
                    score += 2
            if any(
                s in name.lower()
                for s in ("_diffuse", "_albedo", "_basecolor", "_color", "_d.", "_d_")
            ):
                score += 3
            if score > 0:
                candidates.append((name, w, h, score))

        candidates.sort(key=lambda c: -c[3])
        print(f"--- {target} ---")
        if not candidates:
            print("  (no candidate textures matched)")
        for name, w, h, score in candidates[:10]:
            print(f"  score={score:3d}  {name}  ({w}x{h})")
        print()


if __name__ == "__main__":
    main()
