"""Probe the GameObject hierarchy for a composite building prefab.

For each candidate name, find a GameObject by that name, walk its Transform
tree, and print every (GameObject, MeshFilter -> Mesh, has_renderer, depth).
Also report local TRS so we know whether transforms are nontrivial.
"""

from __future__ import annotations

import os
from collections import deque
from typing import Any

import UnityPy

from pinacotheca.extractor import find_game_data

CANDIDATES = [
    "Maurya_Capital",
    "Tamil_Capital",
    "Yuezhi_Capital",
    "AksumCapitol",
    "Hanging_Garden",
    "Kushite Pyramid",
    "Library",  # control: should be a single mesh, not composite
]


def find_transform(go: Any) -> Any | None:
    comps = getattr(go, "m_Component", None) or []
    for entry in comps:
        # ComponentPair (newer) has .component; old format is (class_id, PPtr)
        pptr = getattr(entry, "component", None)
        if pptr is None and isinstance(entry, tuple):
            pptr = entry[1]
        if pptr is None or not bool(pptr):
            continue
        try:
            r = pptr.deref()
            if r.type.name == "Transform":
                return pptr.deref_parse_as_object()
        except Exception:
            pass
    return None


def find_mesh_filter(go: Any) -> tuple[Any | None, Any | None]:
    comps = getattr(go, "m_Component", None) or []
    mf, mr = None, None
    for entry in comps:
        pptr = getattr(entry, "component", None)
        if pptr is None and isinstance(entry, tuple):
            pptr = entry[1]
        if pptr is None or not bool(pptr):
            continue
        try:
            r = pptr.deref()
            t = r.type.name
            if t == "MeshFilter":
                mf = pptr.deref_parse_as_object()
            elif t in ("MeshRenderer", "SkinnedMeshRenderer"):
                mr = pptr.deref_parse_as_object()
        except Exception:
            pass
    return mf, mr


def main() -> None:
    game_data = find_game_data()
    if game_data is None:
        raise SystemExit("Game data not found")
    os.chdir(str(game_data))
    env = UnityPy.Environment()
    env.load_file(str(game_data / "resources.assets"))

    # Find every GameObject named like a candidate, plus a fast lookup
    # of all GOs by name (parsed lazily).
    matches: dict[str, list[Any]] = {c: [] for c in CANDIDATES}
    print("Scanning GameObjects (this can take a minute)...")
    for obj in env.objects:
        if obj.type.name != "GameObject":
            continue
        try:
            name = obj.peek_name()
        except Exception:
            continue
        if name in matches:
            matches[name].append(obj.deref_parse_as_object())

    print()
    for cand in CANDIDATES:
        gos = matches[cand]
        print(f"=== {cand}: {len(gos)} GameObject(s) found ===")
        if not gos:
            continue
        # For each GO, find Transform and walk its tree
        for i, go in enumerate(gos[:2]):  # only first 2 instances
            print(f"  [GO #{i}]")
            t = find_transform(go)
            if t is None:
                print("    no Transform")
                continue

            father_pptr = getattr(t, "m_Father", None)
            is_root = not (father_pptr and bool(father_pptr))
            print(f"    is_root_transform={is_root}")

            # BFS the transform tree; stop early to keep output short
            stack: deque = deque([(t, 0)])
            mesh_count = 0
            seen_mesh_names = set()
            depth_cap = 6
            node_cap = 60
            visited = 0
            while stack and visited < node_cap:
                node, depth = stack.popleft()
                visited += 1
                if depth > depth_cap:
                    continue
                # Find the GO this transform belongs to
                go_pptr = getattr(node, "m_GameObject", None)
                if not (go_pptr and bool(go_pptr)):
                    continue
                child_go = go_pptr.deref_parse_as_object()
                child_name = getattr(child_go, "m_Name", "?")
                mf, mr = find_mesh_filter(child_go)
                if mf is not None:
                    mesh_pptr = getattr(mf, "m_Mesh", None)
                    if mesh_pptr and bool(mesh_pptr):
                        try:
                            mesh = mesh_pptr.deref_parse_as_object()
                            mname = getattr(mesh, "m_Name", "?")
                            seen_mesh_names.add(mname)
                            mesh_count += 1
                        except Exception:
                            mname = "?"
                    else:
                        mname = "(null)"
                    pos = getattr(node, "m_LocalPosition", None)
                    rot = getattr(node, "m_LocalRotation", None)
                    scl = getattr(node, "m_LocalScale", None)

                    def fmt(v: Any) -> str:
                        if v is None:
                            return "?"
                        try:
                            return f"({v.x:+.2f},{v.y:+.2f},{v.z:+.2f}{(',w=' + f'{v.w:+.2f}') if hasattr(v, 'w') else ''})"
                        except Exception:
                            return str(v)

                    print(
                        f"    {'  ' * depth}- {child_name}  mesh={mname}  pos={fmt(pos)} rot={fmt(rot)} scl={fmt(scl)}"
                    )
                # Descend into children
                kids = getattr(node, "m_Children", None) or []
                for k in kids:
                    if not bool(k):
                        continue
                    try:
                        child_t = k.deref_parse_as_object()
                        stack.append((child_t, depth + 1))
                    except Exception:
                        pass

            print(
                f"    -> mesh_filters_in_tree={mesh_count}  unique_meshes={len(seen_mesh_names)}  visited_nodes={visited}"
            )
        print()


if __name__ == "__main__":
    main()
