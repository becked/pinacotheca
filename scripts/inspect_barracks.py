"""
Diagnostic: walk the Barracks prefab, list its parts, and print a Y-bin
histogram so we can see why strip_plinth_from_obj fails on it.

Compares against the Library prefab, which the algorithm successfully
strips.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import UnityPy
from UnityPy.helpers.MeshHelper import MeshHandler

from pinacotheca.extractor import find_game_data
from pinacotheca.prefab import (
    PrefabPart,
    bake_to_obj,
    drop_splat_meshes,
    find_root_gameobject,
    walk_prefab,
)


def _part_name(part: PrefabPart) -> str:
    """Return mesh name + GameObject ancestor name for a part."""
    try:
        mesh = part.mesh_obj.deref_parse_as_object()
        return str(getattr(mesh, "m_Name", "<unnamed>"))
    except Exception:
        return "<unreadable>"


def _part_material_names(part: PrefabPart) -> list[str]:
    names: list[str] = []
    for mp in part.materials:
        try:
            if not bool(mp):
                continue
            mat = mp.deref_parse_as_object()
            names.append(str(getattr(mat, "m_Name", "<unnamed>")))
        except Exception:
            names.append("<unreadable>")
    return names


def _part_y_bounds(part: PrefabPart) -> tuple[float, float, int, str]:
    """Return (y_min_world, y_max_world, vert_count, error_msg) for a part."""
    try:
        mesh = part.mesh_obj.deref_parse_as_object()
    except Exception as e:
        return (0.0, 0.0, 0, f"deref failed: {e}")
    try:
        handler = MeshHandler(mesh)
        handler.process()  # type: ignore[no-untyped-call]
    except Exception as e:
        return (0.0, 0.0, 0, f"MeshHandler failed: {e}")
    if handler.m_VertexCount <= 0 or not handler.m_Vertices:
        # Try UnityPy's high-level Mesh.read().export() instead
        try:
            mr = part.mesh_obj.deref().read()
            obj = mr.export()
            ys: list[float] = []
            for line in obj.split("\n"):
                toks = line.strip().split()
                if len(toks) >= 4 and toks[0] == "v":
                    ys.append(float(toks[2]))
            if ys:
                return (min(ys), max(ys), len(ys), f"raw mesh.export ok ({len(ys)} verts; handler had {handler.m_VertexCount})")
            return (0.0, 0.0, 0, f"both empty (handler={handler.m_VertexCount}, export verts={len(ys)})")
        except Exception as e:
            return (0.0, 0.0, 0, f"handler empty + export failed: {e}")
    m = part.world_matrix
    ys = []
    for vx, vy, vz in handler.m_Vertices:
        wy = m[1, 0] * vx + m[1, 1] * vy + m[1, 2] * vz + m[1, 3]
        ys.append(float(wy))
    return (min(ys), max(ys), len(handler.m_Vertices), "")


def _y_histogram_from_obj(obj_str: str, n_bins: int = 20) -> tuple[list[int], float, float]:
    ys: list[float] = []
    for line in obj_str.split("\n"):
        toks = line.strip().split()
        if len(toks) >= 4 and toks[0] == "v":
            ys.append(float(toks[2]))
    if not ys:
        return ([], 0.0, 0.0)
    y_min = min(ys)
    y_max = max(ys)
    extent = y_max - y_min
    if extent <= 0:
        return ([0] * n_bins, y_min, y_max)
    bin_h = extent / n_bins
    bins = [0] * n_bins
    for y in ys:
        idx = min(int((y - y_min) / bin_h), n_bins - 1)
        bins[idx] += 1
    return (bins, y_min, y_max)


def inspect(env: Any, prefab_name: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"Prefab: {prefab_name}")
    print("=" * 70)
    root = find_root_gameobject(env, prefab_name)
    if root is None:
        print("  NOT FOUND")
        return

    parts = walk_prefab(root)
    print(f"  walk_prefab → {len(parts)} parts")

    # Drop LOD1/LOD2 like the extractor does
    import re
    lod_kept: list[PrefabPart] = []
    for p in parts:
        n = _part_name(p)
        if re.search(r"_LOD[12]$", n, flags=re.IGNORECASE):
            continue
        lod_kept.append(p)
    print(f"  after LOD filter → {len(lod_kept)} parts")

    print("\n  All parts BEFORE splat filter (mesh | materials | y | verts | note):")
    for i, p in enumerate(lod_kept):
        name = _part_name(p)
        mats = _part_material_names(p)
        y_min, y_max, vc, err = _part_y_bounds(p)
        print(f"    [{i:2d}] {name:40s} | {','.join(mats):30s} | y={y_min:7.2f}..{y_max:7.2f} | verts={vc} | {err}")

    kept = drop_splat_meshes(lod_kept)
    print(f"\n  after splat filter → {len(kept)} parts")

    # Bake and analyze full Y histogram
    obj_str = bake_to_obj(kept)
    bins, y_min, y_max = _y_histogram_from_obj(obj_str)
    if not bins:
        print("\n  No verts after bake")
        return

    total_verts = sum(bins)
    extent = y_max - y_min
    threshold_5pct = max(1, int(total_verts * 0.05))
    print(f"\n  Y range: {y_min:.3f} .. {y_max:.3f} (extent {extent:.3f})")
    print(f"  Total verts: {total_verts}")
    print(f"  5% density threshold: {threshold_5pct} verts/bin")
    print(f"  max_cut_fraction=0.50 cap → bins 0..{int(20 * 0.50)} eligible for cut")
    print("\n  Y histogram (20 bins, bottom→top):")
    bin_h = extent / 20
    cut_chosen: int | None = None
    for i, count in enumerate(bins):
        bar = "█" * min(int(count / max(threshold_5pct, 1) * 4), 60)
        flag = ""
        if cut_chosen is None and count >= threshold_5pct and i <= int(20 * 0.50):
            cut_chosen = i
            flag = "  ← cut here (first dense bin in bottom 50%)"
        y_lo = y_min + i * bin_h
        y_hi = y_lo + bin_h
        print(f"    bin {i:2d}  y={y_lo:6.2f}..{y_hi:6.2f}  count={count:5d}  {bar}{flag}")
    if cut_chosen is not None:
        cut_y = y_min + cut_chosen * bin_h
        cut_pct = (cut_y - y_min) / extent * 100
        print(f"\n  Algorithm would cut at y={cut_y:.3f} ({cut_pct:.1f}% of extent)")
    else:
        print("\n  Algorithm finds NO dense bin in bottom 50% → falls back to 5% detection cut")


def main() -> None:
    data_dir = find_game_data()
    if data_dir is None:
        print("Could not find game data directory", file=sys.stderr)
        sys.exit(1)

    print(f"Loading resources.assets from {data_dir}...")
    import os
    os.chdir(str(data_dir))  # required so .resS sidecar files are found
    env = UnityPy.Environment()
    env.load_file(str(data_dir / "resources.assets"))

    inspect(env, "Library")
    inspect(env, "Barracks")


if __name__ == "__main__":
    main()
