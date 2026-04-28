"""Run the verified PVT splat binary parser on a sample of urban tile
prefabs to confirm the same approach works there.

Discovery is unsolved (urban prefab names are inconsistent across nations) —
for this probe we use the names found via texture_inventory.py's GameObject
scan. Production code will discover them via the XML chain instead.
"""

from __future__ import annotations

import os

# Same parser machinery as parse_pvt_splat_binary.py — kept self-contained
# so this probe can be run on its own.
import sys
from collections import deque
from typing import Any

import UnityPy

from pinacotheca.extractor import find_game_data
from pinacotheca.prefab import _components_of, find_root_gameobject

sys.path.insert(
    0, str(__file__).rsplit("/", 1)[0]
)
from parse_pvt_splat_binary import (  # type: ignore
    parse_height_splat,
    parse_pvt_splat,
    resolve_pptr_name,
    script_class,
)

URBAN_PREFABS = [
    # Greece variants
    "Greece_Urban",
    "Greece_Urban 1",
    "Greece_urban_pvt",
    # Rome variants
    "Rome_Urban",
    "RomeUrban",
    "RomeUrbanPVT",
    "Rome_Urban_V2",
    # Other base-game nations
    "Persia_Urban",
    "Carthage_Urban",
    "CarthageUrbanPVT",
    "Babylonia_Urban",
    "Babylon_urbanPVT",
    "Assyria_Urban",
    "AssyriaUrbanPVT",
    "Egypt_Urban",
    "Egypt_UrbanPVT",
    # Already-renderable (DLC/baked) nations — confirm consistency
    "Aksum_Urban",
    "Hittite_Urban",
    "India_UrbanTile",
    "IndiaUrban",
]


def walk_tree(root_go: Any) -> list[Any]:
    out: list[Any] = [root_go]
    t = None
    for pptr in _components_of(root_go):
        try:
            r = pptr.deref()
            if r.type.name == "Transform":
                t = pptr.deref_parse_as_object()
                break
        except Exception:
            pass
    if t is None:
        return out
    stack: deque = deque([t])
    while stack:
        node = stack.popleft()
        for k in getattr(node, "m_Children", None) or []:
            try:
                if not bool(k):
                    continue
                child_t = k.deref_parse_as_object()
                gp = getattr(child_t, "m_GameObject", None)
                if gp and bool(gp):
                    out.append(gp.deref_parse_as_object())
                stack.append(child_t)
            except Exception:
                pass
    return out


def main() -> None:
    game_data = find_game_data()
    assert game_data is not None
    os.chdir(str(game_data))
    env = UnityPy.Environment()
    env.load_file(str(game_data / "globalgamemanagers.assets"))
    env.load_file(str(game_data / "resources.assets"))

    n_prefabs_found = 0
    n_pvt = 0
    n_height = 0

    for prefab_name in URBAN_PREFABS:
        root = find_root_gameobject(env, prefab_name)
        if root is None:
            print(f"\n[URBAN] {prefab_name}: NOT FOUND")
            continue
        n_prefabs_found += 1
        print(f"\n[URBAN] {prefab_name}")
        gos = walk_tree(root)
        print(f"  ({len(gos)} GameObjects)")
        for go in gos:
            go_name = getattr(go, "m_Name", "?")
            for pptr in _components_of(go):
                try:
                    r = pptr.deref()
                    if r.type.name != "MonoBehaviour":
                        continue
                except Exception:
                    continue
                cls = script_class(r)
                if cls not in ("TerrainTexturePVTSplat", "TerrainHeightSplat"):
                    continue
                af = r.assets_file
                try:
                    raw = r.get_raw_data()
                except Exception as e:
                    print(f"  [{go_name}] {cls}: get_raw_data fail: {e}")
                    continue
                if cls == "TerrainTexturePVTSplat":
                    n_pvt += 1
                    f = parse_pvt_splat(raw)
                    albedo = resolve_pptr_name(f.albedo_map, af)
                    alpha = resolve_pptr_name(f.alpha_map, af)
                    normal = resolve_pptr_name(f.normal_map, af)
                    print(
                        f"  [{go_name}] PVT  sort={f.sorting_offset}  "
                        f"albedo={albedo}  alpha={alpha}  normal={normal}  "
                        f"tint={f.albedo_tint}  tiling={f.material_tiling:.2f}  "
                        f"useWorldUVs={f.material_use_world_uvs}  channel={f.alpha_map_channel}"
                    )
                else:
                    n_height += 1
                    h = parse_height_splat(raw)
                    rgb = resolve_pptr_name(h.rgb_heightmap, af)
                    mask = resolve_pptr_name(h.heightmap, af)
                    print(
                        f"  [{go_name}] Height  sort={h.sorting_offset}  "
                        f"rgbHeightmap={rgb}  alphamask={mask}  "
                        f"intensity={h.intensity:+.3f}  tiling={h.tiling:.2f}  "
                        f"middle={h.rgb_heightmap_middle:+.3f}"
                    )

    print(
        f"\n=== SUMMARY: {n_prefabs_found}/{len(URBAN_PREFABS)} prefabs found, "
        f"{n_pvt} PVT splats, {n_height} Height splats parsed ==="
    )


if __name__ == "__main__":
    main()
