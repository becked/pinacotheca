"""
Dump the GameObject/Transform tree of a prefab with full TRS info,
component types, and SMR/MF mesh references. Compare animal vs static
control to find the orientation discrepancy.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path
from typing import Any

import UnityPy

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pinacotheca.extractor import find_game_data
from pinacotheca.prefab import _component_by_type, _components_of, find_root_gameobject


def quat_to_euler(q: Any) -> tuple[float, float, float]:
    """Convert (x,y,z,w) quaternion to Euler XYZ in degrees, ZYX intrinsic."""
    x = float(getattr(q, "x", 0.0))
    y = float(getattr(q, "y", 0.0))
    z = float(getattr(q, "z", 0.0))
    w = float(getattr(q, "w", 1.0))
    # Roll (X), Pitch (Y), Yaw (Z) — Unity uses ZXY intrinsic, but for inspection
    # any consistent decomposition is fine.
    sinr_cosp = 2 * (w * x + y * z)
    cosr_cosp = 1 - 2 * (x * x + y * y)
    rx = math.atan2(sinr_cosp, cosr_cosp)
    sinp = 2 * (w * y - z * x)
    if abs(sinp) >= 1:
        ry = math.copysign(math.pi / 2, sinp)
    else:
        ry = math.asin(sinp)
    siny_cosp = 2 * (w * z + x * y)
    cosy_cosp = 1 - 2 * (y * y + z * z)
    rz = math.atan2(siny_cosp, cosy_cosp)
    return math.degrees(rx), math.degrees(ry), math.degrees(rz)


def list_components(go: Any) -> list[str]:
    out = []
    for pptr in _components_of(go):
        try:
            out.append(pptr.deref().type.name)
        except Exception:
            out.append("?")
    return out


def dump(prefab_name: str, env: Any, max_depth: int = 6) -> None:
    print(f"\n{'=' * 80}\nPREFAB: {prefab_name}\n{'=' * 80}")
    root_go = find_root_gameobject(env, prefab_name)
    if root_go is None:
        print("  not found")
        return
    root_t = _component_by_type(root_go, "Transform")
    if root_t is None:
        print("  no transform")
        return

    def recurse(t: Any, depth: int) -> None:
        if depth > max_depth:
            return
        # GO of this transform
        go_pptr = getattr(t, "m_GameObject", None)
        go_name = "?"
        components: list[str] = []
        tag_str: Any = None
        tag_int: Any = None
        if go_pptr and bool(go_pptr):
            try:
                go = go_pptr.deref_parse_as_object()
                go_name = getattr(go, "m_Name", "?")
                components = list_components(go)
                tag_str = getattr(go, "m_TagString", None)
                tag_int = getattr(go, "m_Tag", None)
            except Exception:
                pass

        pos = getattr(t, "m_LocalPosition", None)
        rot = getattr(t, "m_LocalRotation", None)
        scl = getattr(t, "m_LocalScale", None)
        px, py, pz = (
            float(getattr(pos, "x", 0)),
            float(getattr(pos, "y", 0)),
            float(getattr(pos, "z", 0)),
        )
        sx, sy, sz = (
            float(getattr(scl, "x", 1)),
            float(getattr(scl, "y", 1)),
            float(getattr(scl, "z", 1)),
        )
        ex, ey, ez = quat_to_euler(rot) if rot is not None else (0, 0, 0)

        prefix = "  " * depth
        # Highlight non-trivial X/Z rotations (these would tip a model)
        flag = ""
        if abs(ex) > 1 or abs(ez) > 1:
            flag = "  ***NON-TRIVIAL X/Z ROT***"
        print(
            f"{prefix}- {go_name}  comps={components}  "
            f"tag_str={tag_str!r} tag_int={tag_int!r}  "
            f"pos=({px:.3f},{py:.3f},{pz:.3f})  "
            f"euler(deg)=({ex:.1f},{ey:.1f},{ez:.1f})  "
            f"scl=({sx:.3f},{sy:.3f},{sz:.3f}){flag}"
        )

        for child_pptr in getattr(t, "m_Children", None) or []:
            if not bool(child_pptr):
                continue
            try:
                child_t = child_pptr.deref_parse_as_object()
            except Exception:
                continue
            recurse(child_t, depth + 1)

    recurse(root_t, 0)


def main() -> None:
    game_data = find_game_data()
    if game_data is None:
        print("[ERROR] no game data")
        sys.exit(1)
    os.chdir(str(game_data))
    env = UnityPy.Environment()
    env.load_file(str(game_data / "globalgamemanagers.assets"))
    env.load_file(str(game_data / "resources.assets"))

    for name in ["Goat", "Horse_01", "Cattle", "Crab"]:
        dump(name, env, max_depth=5)


if __name__ == "__main__":
    main()
