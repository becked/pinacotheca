"""
Verify whether animal prefabs carry a SkinnedMeshRenderer with a non-bind
rest pose (approach A is viable) or whether the prefab's bone TRS is the
bind pose itself (approach B needed — sample AnimationClip).

For each (prefab, mesh) we want to compare, for every bone i:

    expected_bone_world_at_bind = inverse(m_BindPoses[i])   # in SMR local space
    actual_bone_world_in_prefab = SMR_local @ walk_to_bone(bone[i])

If these are ~equal for every bone, the prefab transforms ARE the bind
pose. Skinning the m_Mesh against the prefab transforms gives back the
m_Mesh as-is — i.e. what we already render. Approach A would not help;
need B.

If they diverge meaningfully, the prefab was saved with a non-bind rest
pose (typical for editor-visible idle), and approach A would render that
pose.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import UnityPy
from numpy.typing import NDArray

# Repo's own package — needed for find_root_gameobject, trs_matrix, etc.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pinacotheca.extractor import find_game_data
from pinacotheca.prefab import (
    _component_by_type,
    find_root_gameobject,
    trs_matrix,
)


def collect_transform_index(root_t: Any) -> dict[int, tuple[Any, NDArray[np.float64]]]:
    """
    Walk the Transform tree from `root_t` and return a dict mapping each
    Transform's path_id to (transform_obj, world_matrix_relative_to_root).
    """
    out: dict[int, tuple[Any, NDArray[np.float64]]] = {}

    def recurse(t: Any, parent_world: NDArray[np.float64]) -> None:
        local = trs_matrix(
            getattr(t, "m_LocalPosition", None),
            getattr(t, "m_LocalRotation", None),
            getattr(t, "m_LocalScale", None),
        )
        world = parent_world @ local
        # path_id of the underlying object — the SMR's m_Bones[] PPtr
        # carries path_ids we can match against.
        try:
            pid = int(getattr(t, "object_reader", None).path_id)  # type: ignore[union-attr]
        except Exception:
            pid = None
        if pid is not None:
            out[pid] = (t, world.copy())
        for child_pptr in getattr(t, "m_Children", None) or []:
            if not bool(child_pptr):
                continue
            try:
                child_t = child_pptr.deref_parse_as_object()
            except Exception:
                continue
            recurse(child_t, world)

    recurse(root_t, np.eye(4, dtype=np.float64))
    return out


def find_smrs_in_prefab(env: Any, prefab_name: str) -> list[tuple[Any, Any]]:
    """
    Return [(smr_object, owning_gameobject)] for every SkinnedMeshRenderer
    in the named prefab.
    """
    root_go = find_root_gameobject(env, prefab_name)
    if root_go is None:
        print(f"  [ERROR] Prefab '{prefab_name}' not found")
        return []

    root_t = _component_by_type(root_go, "Transform")
    if root_t is None:
        return []

    found: list[tuple[Any, Any]] = []

    def recurse(t: Any) -> None:
        go_pptr = getattr(t, "m_GameObject", None)
        if go_pptr is None or not bool(go_pptr):
            return
        try:
            go = go_pptr.deref_parse_as_object()
        except Exception:
            return
        smr = _component_by_type(go, "SkinnedMeshRenderer")
        if smr is not None:
            found.append((smr, go))
        for child_pptr in getattr(t, "m_Children", None) or []:
            if not bool(child_pptr):
                continue
            try:
                child_t = child_pptr.deref_parse_as_object()
            except Exception:
                continue
            recurse(child_t)

    recurse(root_t)
    return found


def matrix4_from_unity(m: Any) -> NDArray[np.float64]:
    """Convert a Unity Matrix4x4 (e00..e33) to a numpy 4x4."""
    out = np.zeros((4, 4), dtype=np.float64)
    for r in range(4):
        for c in range(4):
            out[r, c] = float(getattr(m, f"e{r}{c}"))
    return out


def smr_local_world_matrix(smr_go: Any, prefab_root_t: Any) -> NDArray[np.float64]:
    """
    Walk from prefab root down to the SMR's GameObject and compute the
    accumulated world matrix (i.e. SMR transform relative to prefab root).
    """
    # Find the SMR's transform path_id and walk to it.
    smr_t = _component_by_type(smr_go, "Transform")
    if smr_t is None:
        return np.eye(4)
    try:
        target_pid = int(smr_t.object_reader.path_id)
    except Exception:
        return np.eye(4)

    idx = collect_transform_index(prefab_root_t)
    if target_pid in idx:
        return idx[target_pid][1]
    return np.eye(4)


def analyze_prefab(env: Any, prefab_name: str, label: str) -> None:
    print(f"\n{'=' * 70}\n{label}: {prefab_name}\n{'=' * 70}")

    root_go = find_root_gameobject(env, prefab_name)
    if root_go is None:
        print("  [ERROR] not found")
        return
    root_t = _component_by_type(root_go, "Transform")
    if root_t is None:
        print("  [ERROR] no root Transform")
        return

    smrs = find_smrs_in_prefab(env, prefab_name)
    if not smrs:
        print("  No SkinnedMeshRenderer found in prefab.")
        return
    print(f"  Found {len(smrs)} SkinnedMeshRenderer(s)")

    transform_idx = collect_transform_index(root_t)

    for i, (smr, smr_go) in enumerate(smrs):
        # SMR's own m_Mesh
        mesh_pptr = getattr(smr, "m_Mesh", None)
        if not mesh_pptr or not bool(mesh_pptr):
            print(f"\n  [SMR {i}] no m_Mesh")
            continue
        try:
            mesh = mesh_pptr.deref_parse_as_object()
        except Exception as e:
            print(f"\n  [SMR {i}] failed to deref m_Mesh: {e}")
            continue

        bones = getattr(smr, "m_Bones", None) or []
        bind_poses = getattr(mesh, "m_BindPose", None) or []
        if not bones:
            print(f"\n  [SMR {i}] no m_Bones — non-skinned (vertices in bind pose are final)")
            continue

        print(f"\n  [SMR {i}] {len(bones)} bones, {len(bind_poses)} bind poses")
        if len(bones) != len(bind_poses):
            print("    (mismatch — using min)")

        n = min(len(bones), len(bind_poses))
        if n == 0:
            continue

        # SMR's own world matrix relative to prefab root.
        smr_world = smr_local_world_matrix(smr_go, root_t)
        smr_world_inv = np.linalg.inv(smr_world)

        # Compare for each bone.
        diffs: list[float] = []
        sample_lines: list[str] = []
        for k in range(n):
            bone_pptr = bones[k]
            if not bool(bone_pptr):
                continue
            try:
                bone_t = bone_pptr.deref_parse_as_object()
            except Exception:
                continue
            try:
                pid = int(bone_t.object_reader.path_id)
            except Exception:
                continue
            if pid not in transform_idx:
                # bone not under prefab root — skip
                continue
            bone_world = transform_idx[pid][1]  # in prefab-root space
            # Express bone in SMR-local space (the frame bind poses live in)
            bone_in_smr_space = smr_world_inv @ bone_world

            bp = matrix4_from_unity(bind_poses[k])
            try:
                bp_inv = np.linalg.inv(bp)
            except np.linalg.LinAlgError:
                continue

            # If prefab is in bind pose: bone_in_smr_space ≈ bp_inv
            delta = bone_in_smr_space - bp_inv
            d = float(np.linalg.norm(delta))
            diffs.append(d)
            if k < 5:
                # Decompose to translation + rotation comparison
                p_actual = bone_in_smr_space[:3, 3]
                p_expect = bp_inv[:3, 3]
                t_diff = float(np.linalg.norm(p_actual - p_expect))
                sample_lines.append(
                    f"    bone[{k:2d}] |Δ matrix|={d:.4f}  "
                    f"|Δ translation|={t_diff:.4f}  "
                    f"actual_t={p_actual.round(3).tolist()}  "
                    f"bind_t={p_expect.round(3).tolist()}"
                )

        if not diffs:
            print("    (no comparable bones)")
            continue

        diffs_arr = np.array(diffs)
        print(f"    bones compared: {len(diffs)}")
        print(
            f"    matrix delta:   min={diffs_arr.min():.4f}  "
            f"mean={diffs_arr.mean():.4f}  max={diffs_arr.max():.4f}"
        )
        for line in sample_lines:
            print(line)

        # Verdict: if max delta is tiny (< 1e-3), prefab IS in bind pose.
        # If it's substantial, prefab carries a non-bind rest pose.
        if diffs_arr.max() < 1e-3:
            print("    VERDICT: prefab transforms == bind pose. Approach A WILL NOT HELP.")
        elif diffs_arr.mean() < 1e-2:
            print(
                "    VERDICT: prefab transforms ~ bind pose (small drift). Approach A unlikely to help."
            )
        else:
            print("    VERDICT: prefab carries a non-bind rest pose. Approach A SHOULD WORK.")


def main() -> None:
    game_data = find_game_data()
    if game_data is None:
        print("[ERROR] Could not find Old World game data")
        sys.exit(1)
    print(f"Game data: {game_data}")

    os.chdir(str(game_data))
    env = UnityPy.Environment()
    env.load_file(str(game_data / "globalgamemanagers.assets"))
    env.load_file(str(game_data / "resources.assets"))

    targets = [
        ("Horse_01", "Animal (skinned)"),
        ("Cattle", "Animal (skinned)"),
        ("Sheep", "Animal (skinned)"),
        ("Pig", "Animal (skinned)"),
        # Sanity: a static resource
        ("Crab", "Static control"),
    ]
    for prefab_name, label in targets:
        try:
            analyze_prefab(env, prefab_name, label)
        except Exception as e:
            print(f"\n[ERROR] {prefab_name}: {e}")


if __name__ == "__main__":
    main()
