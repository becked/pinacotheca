"""Deep dump of Greece_Capital: every component, every mesh-bearing GO's
material names, every MonoBehaviour's resolved script class (even when
the body fails to parse).
"""

from __future__ import annotations

import os
from collections import deque
from typing import Any

import UnityPy

from pinacotheca.extractor import find_game_data
from pinacotheca.prefab import _components_of, find_root_gameobject


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


def script_class_from_typetree(reader: Any) -> str:
    """Extract MonoBehaviour script class via typetree (works even when
    parse_as_object fails on the script-specific tail)."""
    try:
        tt = reader.read_typetree()
    except Exception as e:
        return f"<typetree err: {type(e).__name__}>"
    sp = tt.get("m_Script") if isinstance(tt, dict) else None
    if not isinstance(sp, dict):
        return "<no m_Script>"
    file_id = sp.get("m_FileID", 0)
    path_id = sp.get("m_PathID", 0)
    if not path_id:
        return "<null script>"
    # Resolve PPtr manually via reader.assets_file
    try:
        assets_file = reader.assets_file
        if file_id == 0:
            target = assets_file.files.get(path_id) if hasattr(assets_file, "files") else None
            if target is None:
                target = assets_file.objects.get(path_id) if hasattr(assets_file, "objects") else None
        else:
            ext = assets_file.externals[file_id - 1]
            ext_file = ext.assets_file if hasattr(ext, "assets_file") else None
            if ext_file is not None:
                target = ext_file.files.get(path_id) if hasattr(ext_file, "files") else ext_file.objects.get(path_id)
            else:
                return f"<extern fileID={file_id}>"
        if target is None:
            return f"<not found pathID={path_id}>"
        script_obj = target.parse_as_object()
        return getattr(script_obj, "m_ClassName", None) or getattr(script_obj, "m_Name", None) or "?"
    except Exception as e:
        return f"<resolve err: {type(e).__name__}: {e}>"


def material_names(go: Any) -> list[str]:
    out: list[str] = []
    for pptr in _components_of(go):
        try:
            r = pptr.deref()
            if r.type.name not in ("MeshRenderer", "SkinnedMeshRenderer"):
                continue
            mr = pptr.deref_parse_as_object()
            mats = getattr(mr, "m_Materials", None) or []
            for m in mats:
                if not bool(m):
                    continue
                mo = m.deref_parse_as_object()
                out.append(getattr(mo, "m_Name", "?"))
        except Exception:
            pass
    return out


def main() -> None:
    game_data = find_game_data()
    assert game_data is not None
    os.chdir(str(game_data))
    env = UnityPy.Environment()
    env.load_file(str(game_data / "resources.assets"))

    for prefab_name in ["Greece_Capital", "Rome_Capital", "Egypt_Capital"]:
        root = find_root_gameobject(env, prefab_name)
        if root is None:
            print(f"\n=== {prefab_name}: NOT FOUND ===")
            continue
        gos = walk_tree(root)
        print(f"\n=== {prefab_name} ({len(gos)} GameObjects) ===")
        for go in gos:
            name = getattr(go, "m_Name", "?")
            mats = material_names(go)
            mat_str = f"  materials={mats}" if mats else ""
            print(f"\n  GO: {name!r}{mat_str}")
            for pptr in _components_of(go):
                try:
                    r = pptr.deref()
                    tn = r.type.name
                except Exception:
                    print("    (deref fail)")
                    continue
                if tn == "MonoBehaviour":
                    cls = script_class_from_typetree(r)
                    # Try the body parse to see if it works
                    try:
                        r.parse_as_object()
                        body = "OK"
                    except Exception as e:
                        body = f"FAIL ({type(e).__name__})"
                    print(f"    MonoBehaviour script={cls!r} body_parse={body}")
                else:
                    print(f"    {tn}")


if __name__ == "__main__":
    main()
