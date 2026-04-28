"""Workaround for #2 (texture inventory) and #3 (atlas mode) given that
TerrainTexturePVTSplat MonoBehaviours have no embedded TypeTree and can't
be read through UnityPy's standard API.

Approach:
  - For each per-nation prefix, list every Texture2D in resources.assets
    whose name matches. Categorize by suffix convention (PVT / cap / urban
    / mask / NRM / height / etc.) so we can fill in the doc's table.
  - For #3, also check whether atlas-named textures exist
    (`*Atlas*` / `*atlas*`) — atlas mode would imply per-nation atlases.
  - Also scan all GameObject names matching `*Urban*` / `*Capital*` so we
    have correct prefab names for round 2.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict

import UnityPy

from pinacotheca.extractor import find_game_data

NATIONS = [
    "Greece",
    "greece",
    "Persia",
    "persia",
    "Rome",
    "rome",
    "Carthage",
    "carthage",
    "Babylon",
    "babylon",
    "Assyria",
    "assyria",
    "Egypt",
    "egypt",
    "landEgypt",
    "Aksum",
    "aksum",
    "Hittite",
    "hittite",
    "Maurya",
    "maurya",
    "Tamil",
    "tamil",
    "Yuezhi",
    "yuezhi",
    "India",
    "india",
]


def categorize(name: str) -> str:
    n = name.lower()
    if "atlas" in n:
        return "ATLAS"
    if "mask" in n:
        return "alphamap (mask)"
    if "_h" in n.lower() and (n.endswith("_h") or "height" in n):
        return "height"
    if "height" in n:
        return "height"
    if "nrm" in n or "normal" in n:
        return "normal"
    if n.endswith("_m") or "metallic" in n or "rough" in n:
        return "metallic/roughness"
    if "pvt" in n:
        return "albedo (PVT)"
    if "terrain" in n and "cap" in n:
        return "albedo (cap terrain)"
    if "urban" in n:
        return "albedo (urban)"
    if "cap" in n:
        return "albedo (cap)"
    return "other"


def main() -> None:
    game_data = find_game_data()
    assert game_data is not None
    os.chdir(str(game_data))
    env = UnityPy.Environment()
    env.load_file(str(game_data / "resources.assets"))

    # Pass 1: collect all textures by nation prefix
    by_nation: dict[str, list[tuple[str, str]]] = defaultdict(list)  # nation -> [(name, category)]
    atlas_global: list[str] = []

    for obj in env.objects:
        if obj.type.name != "Texture2D":
            continue
        try:
            data = obj.read()
            name = getattr(data, "m_Name", "")
        except Exception:
            continue
        if not name:
            continue
        if "atlas" in name.lower() and (
            "splat" in name.lower()
            or "pvt" in name.lower()
            or "terrain" in name.lower()
            or any(nat.lower() in name.lower() for nat in NATIONS)
        ):
            atlas_global.append(name)
        for nat in NATIONS:
            if name.startswith(nat) or f"_{nat}" in name or f"-{nat}" in name:
                by_nation[nat.lower()].append((name, categorize(name)))
                break

    print("=" * 72)
    print("TEXTURE INVENTORY BY NATION")
    print("=" * 72)
    # Merge case-variant keys (greece + Greece both → 'greece')
    seen_per_nation: dict[str, set[str]] = defaultdict(set)
    for nat, entries in by_nation.items():
        for name, cat in entries:
            seen_per_nation[nat].add(f"{name}\t{cat}")

    canonical = [
        ("greece", "Greece"),
        ("persia", "Persia"),
        ("rome", "Rome"),
        ("carthage", "Carthage"),
        ("babylon", "Babylon"),
        ("assyria", "Assyria"),
        ("egypt", "Egypt"),
        ("aksum", "Aksum"),
        ("hittite", "Hittite"),
        ("maurya", "Maurya"),
        ("tamil", "Tamil"),
        ("yuezhi", "Yuezhi"),
        ("india", "India"),
    ]
    for key, label in canonical:
        rows = sorted(seen_per_nation.get(key, set()))
        print(f"\n--- {label} ({len(rows)} textures) ---")
        for r in rows:
            print(f"  {r}")

    print("\n" + "=" * 72)
    print("ATLAS-NAMED TEXTURES")
    print("=" * 72)
    if atlas_global:
        for n in sorted(set(atlas_global)):
            print(f"  {n}")
    else:
        print("  (no atlas-named PVT/splat/terrain textures found)")

    # Pass 2: find correct urban tile prefab names by scanning GameObjects
    print("\n" + "=" * 72)
    print("GAMEOBJECT NAMES MATCHING *Urban* / *Capital* / *capital*")
    print("=" * 72)
    pat = re.compile(r"(urban|capital|UrbanTile)", re.IGNORECASE)
    seen_go: set[str] = set()
    for obj in env.objects:
        if obj.type.name != "GameObject":
            continue
        try:
            n = obj.peek_name()
        except Exception:
            continue
        if n and pat.search(n):
            seen_go.add(n)
    for n in sorted(seen_go):
        print(f"  {n}")


if __name__ == "__main__":
    main()
