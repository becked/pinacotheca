"""Brute-force scan a ClutterTransforms MonoBehaviour's raw bytes for
embedded PPtrs (12-byte int32 fileID + int64 pathID) that resolve to Mesh
or Material objects. Tells us what meshes/materials each capital's
ClutterTransforms references — without writing a full hand-parser yet.

Strategy: slide a 12-byte window across the body bytes, attempt to interpret
each as a PPtr, check if it resolves to a Mesh or Material in the env. Report
all hits. False positives possible (random integers that happen to look like
valid PPtrs), so we filter to ones whose pathID actually resolves.
"""

from __future__ import annotations

import os
import struct
import sys
from collections import deque
from typing import Any

import UnityPy

from pinacotheca.extractor import find_game_data
from pinacotheca.prefab import _components_of, find_root_gameobject

sys.path.insert(0, str(__file__).rsplit("/", 1)[0])
from parse_pvt_splat_binary import script_class  # type: ignore

CAPITALS = [
    "Greece_Capital",
    "Rome_Capital",
    "Egypt_Capital",
    "Persia_Capital",
    "Babylonia_Capital",
    "Carthage_Capital",
    "Assyria_Capital",
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


def resolve(file_id: int, path_id: int, assets_file: Any) -> tuple[str, str] | None:
    """Resolve a (file_id, path_id) pair to (type_name, m_Name) or None."""
    if path_id == 0:
        return None
    try:
        if file_id == 0:
            target = assets_file.objects.get(path_id)
        else:
            ext = assets_file.externals[file_id - 1]
            ef = getattr(ext, "assets_file", None) or getattr(ext, "asset_file", None)
            if ef is None:
                env = assets_file.parent
                ext_name = getattr(ext, "path", None)
                if env is not None and ext_name is not None:
                    for fname, fobj in env.files.items():
                        if fname.endswith(ext_name) or ext_name.endswith(fname):
                            ef = fobj
                            break
            if ef is None:
                return None
            target = ef.objects.get(path_id)
        if target is None:
            return None
        type_name = target.type.name
        if type_name not in ("Mesh", "Material", "Texture2D", "GameObject", "MonoScript", "Shader"):
            return None
        try:
            obj = target.parse_as_object()
            name = getattr(obj, "m_Name", None) or "?"
        except Exception:
            name = "<parse fail>"
        return (type_name, name)
    except Exception:
        return None


def scan_pptrs(raw: bytes, assets_file: Any) -> list[tuple[int, str, str, int, int]]:
    """Scan raw bytes for PPtrs at every 4-byte aligned offset. Returns list
    of (offset, type_name, m_Name, file_id, path_id) for resolvable hits."""
    hits: list[tuple[int, str, str, int, int]] = []
    seen_paths: set[tuple[int, int]] = set()
    for off in range(0, len(raw) - 12, 4):
        file_id, path_id = struct.unpack_from("<iq", raw, off)
        if path_id <= 0 or path_id > 100000:  # path IDs in this asset bundle are < ~3000
            continue
        if file_id < 0 or file_id > 10:
            continue
        key = (file_id, path_id)
        if key in seen_paths:
            continue
        seen_paths.add(key)
        result = resolve(file_id, path_id, assets_file)
        if result is None:
            continue
        type_name, name = result
        hits.append((off, type_name, name, file_id, path_id))
    return hits


def main() -> None:
    game_data = find_game_data()
    assert game_data is not None
    os.chdir(str(game_data))
    env = UnityPy.Environment()
    env.load_file(str(game_data / "globalgamemanagers.assets"))
    env.load_file(str(game_data / "resources.assets"))

    for prefab_name in CAPITALS:
        root = find_root_gameobject(env, prefab_name)
        if root is None:
            print(f"\n=== {prefab_name}: NOT FOUND ===")
            continue
        print(f"\n=== {prefab_name} ===")
        for go in walk_tree(root):
            for pptr in _components_of(go):
                try:
                    r = pptr.deref()
                    if r.type.name != "MonoBehaviour":
                        continue
                except Exception:
                    continue
                cls = script_class(r)
                if cls != "ClutterTransforms":
                    continue
                try:
                    raw = r.get_raw_data()
                except Exception:
                    continue
                go_name = getattr(go, "m_Name", "?")
                print(f"\n  [{go_name}] ClutterTransforms ({len(raw)} bytes)")
                hits = scan_pptrs(raw, r.assets_file)

                # Group by type
                by_type: dict[str, list[tuple[int, str, int, int]]] = {}
                for off, tn, name, fid, pid in hits:
                    by_type.setdefault(tn, []).append((off, name, fid, pid))

                for tn in ("Mesh", "Material", "Texture2D", "Shader"):
                    items = by_type.get(tn, [])
                    if not items:
                        continue
                    print(f"    {tn} ({len(items)}):")
                    for off, name, fid, pid in items:
                        print(f"      @0x{off:04x}  {name}  (fid={fid} pid={pid})")


if __name__ == "__main__":
    main()
