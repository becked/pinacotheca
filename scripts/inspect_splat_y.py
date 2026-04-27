"""
Cross-check splat-plane Y vs first-dense-building-bin Y across the full
IMPROVEMENT_MESHES list.

Hypothesis: each prefab's splat planes (TerrainHeightSplat layer in-game)
sit at the same Y as the building's actual ground floor. If true, we can
use the splat plane Y as the cut height instead of the density heuristic.

Output columns:
    name           - improvement output_name
    splat_y_max    - max world Y across all splat-shader parts
    bldg_min_y     - min Y across non-splat building geometry
    bldg_floor_y   - Y at the start of the first dense bin (≥5%) of building geom
    delta          - splat_y_max - bldg_floor_y (close to 0 = good match)
    plinth_pct     - (bldg_floor_y - bldg_min_y) / extent * 100 — how much of
                     the model is plinth that needs cutting
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any

import UnityPy
from UnityPy.helpers.MeshHelper import MeshHandler

from pinacotheca.extractor import IMPROVEMENT_MESHES, find_game_data
from pinacotheca.prefab import (
    PrefabPart,
    _is_splat_material_name,
    find_root_gameobject,
    walk_prefab,
)


def _mesh_name(part: PrefabPart) -> str:
    try:
        m = part.mesh_obj.deref_parse_as_object()
        return str(getattr(m, "m_Name", "<unnamed>"))
    except Exception:
        return "<unreadable>"


def _material_names(part: PrefabPart) -> list[str]:
    out: list[str] = []
    for mp in part.materials:
        try:
            if not bool(mp):
                continue
            mat = mp.deref_parse_as_object()
            out.append(str(getattr(mat, "m_Name", "<unnamed>")))
        except Exception:
            pass
    return out


def _is_splat_part(part: PrefabPart) -> bool:
    return any(_is_splat_material_name(n) for n in _material_names(part))


def _world_ys(part: PrefabPart) -> list[float]:
    try:
        mesh = part.mesh_obj.deref_parse_as_object()
        h = MeshHandler(mesh)
        h.process()  # type: ignore[no-untyped-call]
    except Exception:
        return []
    if h.m_VertexCount <= 0 or not h.m_Vertices:
        return []
    m = part.world_matrix
    return [float(m[1, 0] * vx + m[1, 1] * vy + m[1, 2] * vz + m[1, 3]) for vx, vy, vz in h.m_Vertices]


def _y_histogram(ys: list[float], n_bins: int = 20) -> tuple[list[int], float, float]:
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


def _first_dense_bin_y(ys: list[float], density_threshold: float = 0.05, n_bins: int = 20) -> float | None:
    bins, y_min, y_max = _y_histogram(ys, n_bins)
    if not bins:
        return None
    extent = y_max - y_min
    threshold = max(1, int(len(ys) * density_threshold))
    bin_h = extent / n_bins
    for i, count in enumerate(bins):
        if count >= threshold:
            return y_min + i * bin_h
    return None


def analyze(env: Any, prefab_name: str) -> dict[str, Any]:
    root = find_root_gameobject(env, prefab_name)
    if root is None:
        return {"status": "NO_PREFAB"}
    parts = walk_prefab(root)
    # Drop LOD1/LOD2
    parts = [p for p in parts if not re.search(r"_LOD[12]$", _mesh_name(p), flags=re.IGNORECASE)]
    if not parts:
        return {"status": "NO_PARTS"}

    # Bucket splat parts by material category so we can see whether
    # WaterNoFoam / BathWater (water surfaces) sit at different Y than
    # SplatHeightDefault / SplatClutterDefault (ground stamps).
    height_ys: list[float] = []  # SplatHeightDefault — the ground heightmap stamp
    other_splat_ys: list[float] = []  # SplatClutter*, SplatTexture*, etc
    water_ys: list[float] = []  # WaterNoFoam, BathWater
    bldg_ys: list[float] = []
    splat_breakdown: list[tuple[str, float]] = []  # (mat_name, max_y)
    for p in parts:
        ys = _world_ys(p)
        if not ys:
            continue
        mats = _material_names(p)
        if _is_splat_part(p):
            for m in mats:
                if _is_splat_material_name(m):
                    splat_breakdown.append((m, max(ys)))
            primary = mats[0] if mats else ""
            if primary in ("WaterNoFoam", "BathWater"):
                water_ys.extend(ys)
            elif primary == "SplatHeightDefault":
                height_ys.extend(ys)
            else:
                other_splat_ys.extend(ys)
        else:
            bldg_ys.extend(ys)

    # Pick the best ground-line proxy: prefer SplatHeightDefault, fall back
    # to other terrain splats (Clutter/Texture). Ignore water surfaces.
    splat_ys = height_ys or other_splat_ys

    if not bldg_ys:
        return {"status": "NO_BUILDING_GEOM"}

    bldg_min = min(bldg_ys)
    bldg_max = max(bldg_ys)
    extent = bldg_max - bldg_min
    floor_y = _first_dense_bin_y(bldg_ys)
    splat_y_max = max(splat_ys) if splat_ys else None

    delta = (splat_y_max - floor_y) if (splat_y_max is not None and floor_y is not None) else None
    plinth_pct = ((floor_y - bldg_min) / extent * 100) if (floor_y is not None and extent > 0) else None

    return {
        "status": "OK",
        "splat_count": len(splat_breakdown),
        "splat_y_max": splat_y_max,
        "splat_breakdown": splat_breakdown,
        "water_y_max": max(water_ys) if water_ys else None,
        "bldg_min": bldg_min,
        "bldg_max": bldg_max,
        "bldg_floor_y": floor_y,
        "delta": delta,
        "plinth_pct": plinth_pct,
    }


def main() -> None:
    data_dir = find_game_data()
    if data_dir is None:
        print("Could not find game data directory", file=sys.stderr)
        sys.exit(1)

    os.chdir(str(data_dir))
    print(f"Loading resources.assets from {data_dir}...")
    env = UnityPy.Environment()
    env.load_file(str(data_dir / "resources.assets"))

    print()
    hdr = (
        f"{'output_name':<22} {'splats':<6} {'splat_y':>8} {'bldg_min':>9} "
        f"{'bldg_max':>9} {'floor_y':>8} {'delta':>7} {'plinth%':>8} {'status'}"
    )
    print(hdr)
    print("-" * len(hdr))

    matches = 0
    near_matches = 0
    misses = 0
    no_splats = 0
    no_prefab = 0

    for mesh_name, output_name in IMPROVEMENT_MESHES:
        prefab_base = re.sub(r"_LOD\d+$", "", mesh_name, flags=re.IGNORECASE)
        info = analyze(env, prefab_base)

        if info["status"] != "OK":
            print(f"{output_name:<22} {'-':<6} {'':>8} {'':>9} {'':>9} {'':>8} {'':>7} {'':>8} {info['status']}")
            if info["status"] == "NO_PREFAB":
                no_prefab += 1
            continue

        sy = info["splat_y_max"]
        floor = info["bldg_floor_y"]
        delta = info["delta"]
        pp = info["plinth_pct"]

        sy_str = f"{sy:>8.3f}" if sy is not None else f"{'-':>8}"
        floor_str = f"{floor:>8.3f}" if floor is not None else f"{'-':>8}"
        delta_str = f"{delta:>7.3f}" if delta is not None else f"{'-':>7}"
        pp_str = f"{pp:>7.1f}%" if pp is not None else f"{'-':>8}"

        # Classify match quality
        tag = ""
        if sy is None:
            tag = "NO_SPLAT"
            no_splats += 1
        elif delta is not None:
            ad = abs(delta)
            if ad < 0.10:
                tag = "MATCH"
                matches += 1
            elif ad < 0.30:
                tag = "NEAR"
                near_matches += 1
            else:
                tag = f"MISS({delta:+.2f})"
                misses += 1

        print(
            f"{output_name:<22} {info['splat_count']:<6d} {sy_str} {info['bldg_min']:>9.3f} "
            f"{info['bldg_max']:>9.3f} {floor_str} {delta_str} {pp_str}  {tag}"
        )
        # Detail line for non-MATCH cases: show which splat materials at which Y
        if tag not in ("MATCH", "") and info.get("splat_breakdown"):
            for mat, y in info["splat_breakdown"]:
                print(f"      └─ {mat:35s} y={y:.3f}")
            if info.get("water_y_max") is not None:
                print(f"      └─ (water_y_max={info['water_y_max']:.3f})")

    print()
    print(f"Summary: {matches} match (Δ<0.10) | {near_matches} near (Δ<0.30) | "
          f"{misses} miss (Δ≥0.30) | {no_splats} no_splat | {no_prefab} no_prefab")


if __name__ == "__main__":
    main()
