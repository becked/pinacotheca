"""
Two questions:
  (1) What's the AABB of the raw mesh vertices for horse_01 / CowDairy /
      Crab_GEO? This tells us how the mesh is authored — if it's tall on
      Y_local, the mesh-local frame has Y as up; if it's tall on Z_local,
      the mesh is authored lying flat.
  (2) What's the Animator referencing — what AnimationClip, and what
      transform curves does it carry? Goal: see if the AnimationClip
      animates the SMR's local rotation to put the horse upright.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import UnityPy

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pinacotheca.extractor import find_game_data
from pinacotheca.prefab import _component_by_type, find_root_gameobject


def find_smr_under(t: Any, depth: int = 5) -> list[Any]:
    """Return [smr_obj] for every SkinnedMeshRenderer in this subtree."""
    out: list[Any] = []
    if depth < 0:
        return out
    go_pptr = getattr(t, "m_GameObject", None)
    if go_pptr and bool(go_pptr):
        try:
            go = go_pptr.deref_parse_as_object()
            smr = _component_by_type(go, "SkinnedMeshRenderer")
            if smr is not None:
                out.append(smr)
        except Exception:
            pass
    for c in getattr(t, "m_Children", None) or []:
        if not bool(c):
            continue
        try:
            ct = c.deref_parse_as_object()
        except Exception:
            continue
        out.extend(find_smr_under(ct, depth - 1))
    return out


def mesh_aabb(mesh: Any) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    from UnityPy.helpers.MeshHelper import MeshHandler

    handler = MeshHandler(mesh)
    handler.process()  # type: ignore[no-untyped-call]
    if handler.m_VertexCount <= 0 or not handler.m_Vertices:
        return ((0, 0, 0), (0, 0, 0))
    arr = np.asarray(handler.m_Vertices, dtype=np.float32)
    return (tuple(arr.min(axis=0).tolist()), tuple(arr.max(axis=0).tolist()))


def dump_mesh_info(env: Any, prefab_name: str) -> None:
    print(f"\n=== Mesh AABB for {prefab_name} ===")
    root_go = find_root_gameobject(env, prefab_name)
    if root_go is None:
        print("  not found")
        return
    root_t = _component_by_type(root_go, "Transform")
    if root_t is None:
        return

    smrs = find_smr_under(root_t, depth=8)
    seen_meshes = set()
    for smr in smrs:
        mp = getattr(smr, "m_Mesh", None)
        if not mp or not bool(mp):
            continue
        try:
            pid = int(mp.path_id)
        except Exception:
            pid = None
        if pid in seen_meshes:
            continue
        seen_meshes.add(pid)
        try:
            mesh = mp.deref_parse_as_object()
            mesh_name = getattr(mesh, "m_Name", "?")
        except Exception as e:
            print(f"  failed deref: {e}")
            continue
        try:
            mn, mx = mesh_aabb(mesh)
            ext = (mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2])
            print(
                f"  mesh={mesh_name}  pid={pid}  "
                f"min=({mn[0]:.2f},{mn[1]:.2f},{mn[2]:.2f}) "
                f"max=({mx[0]:.2f},{mx[1]:.2f},{mx[2]:.2f}) "
                f"extent=({ext[0]:.2f},{ext[1]:.2f},{ext[2]:.2f})  "
                f"longest_axis={'XYZ'[int(np.argmax(ext))]}"
            )
        except Exception as e:
            print(f"  AABB failed for {mesh_name}: {e}")


def dump_animator_info(env: Any, prefab_name: str) -> None:
    """Find Animator components and print referenced controller/clips."""
    print(f"\n=== Animator info for {prefab_name} ===")
    root_go = find_root_gameobject(env, prefab_name)
    if root_go is None:
        return
    root_t = _component_by_type(root_go, "Transform")
    if root_t is None:
        return

    def recurse(t: Any, depth: int = 0) -> None:
        if depth > 5:
            return
        go_pptr = getattr(t, "m_GameObject", None)
        if not (go_pptr and bool(go_pptr)):
            return
        try:
            go = go_pptr.deref_parse_as_object()
        except Exception:
            return
        animator = _component_by_type(go, "Animator")
        if animator is not None:
            controller_pptr = getattr(animator, "m_Controller", None)
            avatar_pptr = getattr(animator, "m_Avatar", None)
            print(f"  Animator on {getattr(go, 'm_Name', '?')}:")
            if controller_pptr and bool(controller_pptr):
                try:
                    ctrl = controller_pptr.deref_parse_as_object()
                    ctype = controller_pptr.deref().type.name
                    cname = getattr(ctrl, "m_Name", "?")
                    print(f"    Controller: type={ctype} name={cname}")
                    # Try to surface AnimationClip references
                    clips = getattr(ctrl, "m_AnimationClips", None)
                    if clips:
                        for cp in clips:
                            if bool(cp):
                                try:
                                    cl = cp.deref_parse_as_object()
                                    print(f"      Clip: {getattr(cl, 'm_Name', '?')}")
                                except Exception:
                                    pass
                except Exception as e:
                    print(f"    Controller deref failed: {e}")
            else:
                print("    Controller: <none>")
            if avatar_pptr and bool(avatar_pptr):
                try:
                    av = avatar_pptr.deref_parse_as_object()
                    print(f"    Avatar: {getattr(av, 'm_Name', '?')}")
                except Exception:
                    pass
        for c in getattr(t, "m_Children", None) or []:
            if not bool(c):
                continue
            try:
                ct = c.deref_parse_as_object()
            except Exception:
                continue
            recurse(ct, depth + 1)

    recurse(root_t)


def find_clip_curves(env: Any, clip_name_substr: str) -> None:
    """
    Locate an AnimationClip by name substring and print its
    EulerCurves / RotationCurves / FloatCurves to see if it animates
    the SMR/rig transform rotation.
    """
    print(f"\n=== AnimationClip search: '{clip_name_substr}' ===")
    found = False
    for obj in env.objects:
        if obj.type.name != "AnimationClip":
            continue
        try:
            name = obj.peek_name()
        except Exception:
            continue
        if not name or clip_name_substr.lower() not in name.lower():
            continue
        found = True
        try:
            clip = obj.parse_as_object()
        except Exception as e:
            print(f"  {name}: parse failed {e}")
            continue
        rcurves = getattr(clip, "m_RotationCurves", None) or []
        ecurves = getattr(clip, "m_EulerCurves", None) or []
        pcurves = getattr(clip, "m_PositionCurves", None) or []
        fcurves = getattr(clip, "m_FloatCurves", None) or []
        print(
            f"  {name} pid={obj.path_id}  "
            f"rot={len(rcurves)} euler={len(ecurves)} pos={len(pcurves)} float={len(fcurves)}"
        )
        # Show first-frame rotation values for any rotation/euler curves.
        for label, curves in (("ROT", rcurves), ("EULER", ecurves)):
            for i, cur in enumerate(curves[:6]):
                path = getattr(cur, "path", "?")
                inner_curve = getattr(cur, "curve", None)
                kf = getattr(inner_curve, "m_Curve", None) if inner_curve else None
                if kf and len(kf) > 0:
                    val0 = getattr(kf[0], "value", None)
                    if val0 is not None:
                        # Extract x,y,z[,w]
                        vx = getattr(val0, "x", None)
                        vy = getattr(val0, "y", None)
                        vz = getattr(val0, "z", None)
                        vw = getattr(val0, "w", None)
                        print(
                            f"    [{label} {i}] path='{path}'  "
                            f"frame0=({vx},{vy},{vz}{',w=' + str(vw) if vw is not None else ''})"
                        )
        if found:
            break  # one is enough for inspection
    if not found:
        print(f"  no clip matching '{clip_name_substr}'")


def main() -> None:
    game_data = find_game_data()
    if game_data is None:
        print("[ERROR] no game data")
        sys.exit(1)
    os.chdir(str(game_data))
    env = UnityPy.Environment()
    env.load_file(str(game_data / "globalgamemanagers.assets"))
    env.load_file(str(game_data / "resources.assets"))

    for name in [
        "Horse_01",
        "Cattle",
        "Sheep",
        "Pig",
        "Goat",
        "Camel",
        "Elephant",
        "Deer",
        "Furs",
    ]:
        dump_mesh_info(env, name)


if __name__ == "__main__":
    main()
