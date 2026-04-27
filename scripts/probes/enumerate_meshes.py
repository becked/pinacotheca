"""Enumerate all Mesh objects in Old World's resources.assets.

Outputs a JSON file with every mesh name, plus a summary by inferred category.
Run with: python scripts/probes/enumerate_meshes.py
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path

import UnityPy

from pinacotheca.extractor import find_game_data

OUTPUT_PATH = Path(__file__).parent / "meshes.json"


def classify(name: str) -> str:
    """Heuristic category for a mesh name. Tweak iteratively."""
    n = name.lower()

    # Unit suffixes/markers
    if n.endswith("_geo") or n.endswith("_geo2") or "_geo_" in n:
        return "unit_geo"
    if "warrior" in n or "archer" in n or "horseman" in n or "spearman" in n:
        return "unit_keyword"
    if "elephant" in n or "chariot" in n or "ballista" in n or "catapult" in n:
        return "siege_or_special"
    if "settler" in n or "worker" in n or "scout" in n or "disciple" in n:
        return "noncombat_unit"

    # Buildings / improvements
    building_kw = (
        "library", "barracks", "shrine", "temple", "palace", "forum",
        "market", "monument", "garden", "wonder", "theater", "amphitheater",
        "harbor", "lighthouse", "academy", "court", "shipwright", "stable",
        "armory", "wall", "gate", "tower", "tomb", "bath", "aqueduct",
        "obelisk", "pyramid", "ziggurat", "sanctuary", "altar",
    )
    if any(k in n for k in building_kw):
        return "urban_improvement"

    rural_kw = (
        "farm", "pasture", "lumbermill", "lumber_mill", "mine", "quarry",
        "watermill", "water_mill", "windmill", "wind_mill", "orchard",
        "vineyard", "fishing", "hunting", "camp", "outpost", "trading",
        "brickworks", "kiln", "stoneworks", "ironworks", "olive", "wheat",
    )
    if any(k in n for k in rural_kw):
        return "rural_improvement"

    # Tile / terrain features
    terrain_kw = (
        "tree", "rock", "cliff", "river", "hill", "mountain", "forest",
        "desert", "tundra", "jungle", "ocean", "lake", "tile_", "_tile",
    )
    if any(k in n for k in terrain_kw):
        return "terrain"

    # Infrastructure
    if any(k in n for k in ("road", "bridge", "fortification")):
        return "infrastructure"

    # Resources/animals on the map
    if any(k in n for k in ("cattle", "sheep", "goat", "horse", "deer", "boar", "fish")):
        return "map_animal_or_resource"

    # UI / FX / skybox / camera misc
    if any(k in n for k in ("ui", "icon", "fx", "particle", "skybox", "decal")):
        return "ui_or_fx"

    return "other"


def main() -> None:
    game_data = find_game_data()
    if game_data is None:
        raise SystemExit("Game data not found")

    print(f"Loading {game_data / 'resources.assets'}...")
    os.chdir(str(game_data))

    env = UnityPy.Environment()
    env.load_file(str(game_data / "resources.assets"))

    meshes: list[dict[str, object]] = []
    unreadable = 0

    for obj in env.objects:
        if obj.type.name != "Mesh":
            continue
        try:
            data = obj.read()
            name = getattr(data, "m_Name", "") or ""
            if not name:
                continue
            vertex_count = getattr(data, "m_VertexCount", None)
            sub_meshes = getattr(data, "m_SubMeshes", None)
            sub_count = len(sub_meshes) if sub_meshes is not None else None
            meshes.append({
                "name": name,
                "vertices": vertex_count,
                "submeshes": sub_count,
                "category": classify(name),
            })
        except Exception:
            unreadable += 1

    by_cat = Counter(m["category"] for m in meshes)

    # Sort meshes by category then name for readability
    meshes.sort(key=lambda m: (str(m["category"]), str(m["name"]).lower()))

    payload = {
        "total_meshes": len(meshes),
        "unreadable": unreadable,
        "by_category": dict(by_cat.most_common()),
        "meshes": meshes,
    }

    OUTPUT_PATH.write_text(json.dumps(payload, indent=2))

    print(f"\nTotal meshes: {len(meshes)}")
    print(f"Unreadable: {unreadable}")
    print("\nBy category:")
    for cat, count in by_cat.most_common():
        print(f"  {cat}: {count}")
    print(f"\nWrote: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
