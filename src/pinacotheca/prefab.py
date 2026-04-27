"""
GameObject/Transform prefab traversal for composite buildings.

Composite buildings (DLC capitals like Maurya_Capital, wonders like
Hanging_Garden) are stored as Unity prefabs: a tree of GameObjects with
Transform components and MeshFilter leaves pointing to multiple sub-meshes.
Rendering the named Mesh asset alone produces an exploded scatter — the
sub-mesh vertices are stored in each GameObject's local space and only
assemble correctly when the Transform hierarchy is walked.

This module walks the hierarchy, bakes per-leaf world transforms into
vertex positions, and emits a combined OBJ string consumable by the
existing renderer pipeline.

Coordinate conventions:
    Unity uses left-handed Y-up. All matrix composition here stays in
    Unity's native space. The handedness flip (negate X on positions
    and normals; reverse triangle winding) happens once on final OBJ
    emission, mirroring UnityPy's MeshExporter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

if TYPE_CHECKING:
    from PIL import Image


@dataclass
class PrefabPart:
    """One MeshFilter leaf in a prefab: its mesh, world matrix, materials."""

    mesh_obj: Any  # UnityPy Mesh ObjectReader (lazy; deref later)
    world_matrix: NDArray[np.float64]  # 4x4 in Unity-space
    materials: list[Any]  # list of Material PPtrs (deref'd lazily)


def _components_of(go: Any) -> list[Any]:
    """
    Return the list of component PPtrs from a GameObject, normalizing
    across UnityPy's ComponentPair (newer) and (class_id, PPtr) tuple
    (older) shapes. Filters out null PPtrs.
    """
    raw = getattr(go, "m_Component", None) or []
    out: list[Any] = []
    for entry in raw:
        pptr = getattr(entry, "component", None)
        if pptr is None and isinstance(entry, tuple) and len(entry) >= 2:
            pptr = entry[1]
        if pptr is None:
            continue
        try:
            if not bool(pptr):
                continue
        except Exception:
            continue
        out.append(pptr)
    return out


def _component_by_type(go: Any, type_name: str) -> Any | None:
    """Return the first component of the given type as a parsed object, or None."""
    for pptr in _components_of(go):
        try:
            if pptr.deref().type.name == type_name:
                return pptr.deref_parse_as_object()
        except Exception:
            continue
    return None


def find_root_gameobject(env: Any, name: str) -> Any | None:
    """
    Find a prefab root GameObject by name.

    Scans every GameObject in the environment using cheap peek_name() so
    we don't fully parse mismatches. Among matches, returns the first
    one whose Transform has no parent (m_Father is null), i.e. the
    prefab root. Falls back to any matching GameObject if no clear root
    exists.
    """
    candidates: list[Any] = []
    for obj in env.objects:
        if obj.type.name != "GameObject":
            continue
        try:
            if obj.peek_name() == name:
                candidates.append(obj)
        except Exception:
            continue

    if not candidates:
        return None

    for cand_reader in candidates:
        try:
            # ObjectReader uses parse_as_object(); PPtr uses deref_parse_as_object().
            go = cand_reader.parse_as_object()
            t = _component_by_type(go, "Transform")
            if t is None:
                continue
            father = getattr(t, "m_Father", None)
            if father is None or not bool(father):
                return go
        except Exception:
            continue

    # No clear root found; return the first parseable match.
    try:
        return candidates[0].parse_as_object()
    except Exception:
        return None


def quat_to_mat3(q: Any) -> NDArray[np.float64]:
    """
    Convert a Unity quaternion (x, y, z, w) to a 3x3 rotation matrix.

    Unity stores rotations as (x, y, z, w). The matrix below is the
    standard right-handed quaternion-to-matrix formula. It works for
    Unity left-handed coords too because the conversion to right-handed
    happens later via X-axis negation, which commutes with this matrix.
    """
    x = float(getattr(q, "x", 0.0))
    y = float(getattr(q, "y", 0.0))
    z = float(getattr(q, "z", 0.0))
    w = float(getattr(q, "w", 1.0))
    # Normalize to guard against floating-point drift.
    n = (x * x + y * y + z * z + w * w) ** 0.5
    if n > 0:
        x, y, z, w = x / n, y / n, z / n, w / n
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def trs_matrix(pos: Any, rot: Any, scale: Any) -> NDArray[np.float64]:
    """
    Build a 4x4 TRS (translate * rotate * scale) matrix.

    Applied to a column vector v = [x, y, z, 1]^T as M @ v, this scales
    first, then rotates, then translates — the Unity convention.
    """
    m = np.eye(4, dtype=np.float64)
    r = quat_to_mat3(rot)
    sx = float(getattr(scale, "x", 1.0))
    sy = float(getattr(scale, "y", 1.0))
    sz = float(getattr(scale, "z", 1.0))
    m[:3, :3] = r * np.array([sx, sy, sz], dtype=np.float64)  # column-wise scale
    m[0, 3] = float(getattr(pos, "x", 0.0))
    m[1, 3] = float(getattr(pos, "y", 0.0))
    m[2, 3] = float(getattr(pos, "z", 0.0))
    return m


def walk_prefab(root_go: Any) -> list[PrefabPart]:
    """
    Walk the Transform tree from a root GameObject and collect every
    active MeshFilter leaf with its baked world matrix and materials.

    Skips inactive GameObjects (m_IsActive == False). Cycles or missing
    Transforms abort that branch.
    """
    parts: list[PrefabPart] = []

    root_t = _component_by_type(root_go, "Transform")
    if root_t is None:
        return parts

    def recurse(transform: Any, parent_world: NDArray[np.float64]) -> None:
        # Compute this node's world matrix
        local = trs_matrix(
            getattr(transform, "m_LocalPosition", None),
            getattr(transform, "m_LocalRotation", None),
            getattr(transform, "m_LocalScale", None),
        )
        world = parent_world @ local

        # Find this transform's owning GameObject
        go_pptr = getattr(transform, "m_GameObject", None)
        if go_pptr is None or not bool(go_pptr):
            return
        try:
            go = go_pptr.deref_parse_as_object()
        except Exception:
            return

        # Skip inactive GameObjects
        if getattr(go, "m_IsActive", True) is False:
            return

        # Capture MeshFilter + sibling MeshRenderer materials (if any)
        mf = _component_by_type(go, "MeshFilter")
        if mf is not None:
            mesh_pptr = getattr(mf, "m_Mesh", None)
            if mesh_pptr is not None and bool(mesh_pptr):
                renderer = _component_by_type(go, "MeshRenderer") or _component_by_type(
                    go, "SkinnedMeshRenderer"
                )
                materials: list[Any] = []
                if renderer is not None:
                    raw_mats = getattr(renderer, "m_Materials", None) or []
                    for mp in raw_mats:
                        if bool(mp):
                            materials.append(mp)
                parts.append(
                    PrefabPart(
                        mesh_obj=mesh_pptr,
                        world_matrix=world.copy(),
                        materials=materials,
                    )
                )

        # Recurse into children
        children = getattr(transform, "m_Children", None) or []
        for child_pptr in children:
            if not bool(child_pptr):
                continue
            try:
                child_t = child_pptr.deref_parse_as_object()
            except Exception:
                continue
            recurse(child_t, world)

    recurse(root_t, np.eye(4, dtype=np.float64))
    return parts


def _normal_matrix(m3: NDArray[np.float64]) -> NDArray[np.float64]:
    """Inverse-transpose of a 3x3 matrix, for normal transforms."""
    try:
        return np.linalg.inv(m3).T.astype(np.float64)
    except np.linalg.LinAlgError:
        return m3  # singular; fall back to direct apply


def bake_to_obj(parts: list[PrefabPart]) -> str:
    """
    Bake parts into a single OBJ string in OpenGL right-handed space.

    Applies each part's world matrix to its vertices (inverse-transpose
    for normals), then performs the Unity → right-handed conversion:
    negate X on positions and normals, reverse triangle winding. The
    result is consumable by `renderer.parse_obj()` directly.

    Parts with no usable mesh data are skipped silently.
    """
    from UnityPy.helpers.MeshHelper import MeshHandler

    sb: list[str] = []
    sb.append("g prefab\n")

    v_offset = 0  # cumulative vertex index offset for face references
    vt_offset = 0
    vn_offset = 0

    for part_idx, part in enumerate(parts):
        try:
            mesh = part.mesh_obj.deref_parse_as_object()
        except Exception:
            continue

        try:
            handler = MeshHandler(mesh)
            handler.process()  # type: ignore[no-untyped-call]
        except Exception:
            continue

        if handler.m_VertexCount <= 0 or not handler.m_Vertices:
            continue

        m = part.world_matrix
        m3 = m[:3, :3]
        nm3 = _normal_matrix(m3)
        # Negative determinant means the part is mirrored — reverse winding
        flip_winding = float(np.linalg.det(m3)) < 0.0

        # Vertices: world-space then X-negation for right-handed OBJ
        for vx, vy, vz in handler.m_Vertices:
            wx = m[0, 0] * vx + m[0, 1] * vy + m[0, 2] * vz + m[0, 3]
            wy = m[1, 0] * vx + m[1, 1] * vy + m[1, 2] * vz + m[1, 3]
            wz = m[2, 0] * vx + m[2, 1] * vy + m[2, 2] * vz + m[2, 3]
            sb.append(f"v {-wx:.9G} {wy:.9G} {wz:.9G}\n")

        if handler.m_UV0:
            for uv in handler.m_UV0:
                sb.append(f"vt {uv[0]:.9G} {uv[1]:.9G}\n")
        if handler.m_Normals:
            for n in handler.m_Normals:
                nx, ny, nz = float(n[0]), float(n[1]), float(n[2])
                wnx = nm3[0, 0] * nx + nm3[0, 1] * ny + nm3[0, 2] * nz
                wny = nm3[1, 0] * nx + nm3[1, 1] * ny + nm3[1, 2] * nz
                wnz = nm3[2, 0] * nx + nm3[2, 1] * ny + nm3[2, 2] * nz
                sb.append(f"vn {-wnx:.9G} {wny:.9G} {wnz:.9G}\n")

        # Faces — reverse winding for right-handed OBJ. Optionally double-
        # reverse if part has negative scale (cancels back to left-handed
        # CCW relative to the flipped vertices).
        try:
            tris_per_sub = handler.get_triangles()
        except Exception:
            tris_per_sub = []
        for sub_idx, triangles in enumerate(tris_per_sub):
            sb.append(f"g part{part_idx}_sub{sub_idx}\n")
            for tri in triangles:
                if len(tri) < 3:
                    continue
                a, b, c = tri[0] + v_offset + 1, tri[1] + v_offset + 1, tri[2] + v_offset + 1
                # MeshExporter emits (c, b, a). If part is mirrored, emit
                # (a, b, c) to undo the second flip.
                if flip_winding:
                    sb.append(f"f {a}/{a}/{a} {b}/{b}/{b} {c}/{c}/{c}\n")
                else:
                    sb.append(f"f {c}/{c}/{c} {b}/{b}/{b} {a}/{a}/{a}\n")

        v_offset += len(handler.m_Vertices)
        if handler.m_UV0:
            vt_offset += len(handler.m_UV0)
        if handler.m_Normals:
            vn_offset += len(handler.m_Normals)
        # Suppress unused-variable warnings; offsets retained for
        # future per-channel index arithmetic if needed.
        _ = vt_offset
        _ = vn_offset

    return "".join(sb)


# Material property keys to probe for the diffuse/albedo texture, in
# order of preference. HDRP first (newer Indus DLC assets), then URP,
# then legacy main texture, then HDRP base color.
_DIFFUSE_PROPERTY_KEYS = ("_BaseColorMap", "_BaseMap", "_MainTex", "_BaseColor")


def find_diffuse_for_prefab(parts: list[PrefabPart]) -> Image.Image | None:
    """
    Pick the largest-area diffuse texture across all the prefab's
    materials. Returns a PIL Image or None if no usable texture is
    found.

    Capitals overwhelmingly use one shared albedo across parts; pick
    the largest by pixel area to avoid grabbing a small detail texture.
    """
    best_image: Any = None
    best_area = 0
    seen_pathids: set[int] = set()

    for part in parts:
        for mat_pptr in part.materials:
            try:
                if not bool(mat_pptr):
                    continue
                material = mat_pptr.deref_parse_as_object()
            except Exception:
                continue
            saved = getattr(material, "m_SavedProperties", None)
            if saved is None:
                continue
            tex_envs = getattr(saved, "m_TexEnvs", None) or []
            for entry in tex_envs:
                # entry is a (FastPropertyName-or-str, UnityTexEnv) tuple
                if isinstance(entry, tuple) and len(entry) >= 2:
                    key, tex_env = entry[0], entry[1]
                else:
                    key = getattr(entry, "first", None) or getattr(entry, "key", None)
                    tex_env = getattr(entry, "second", None) or getattr(entry, "value", None)
                key_name = key if isinstance(key, str) else getattr(key, "name", str(key))
                if key_name not in _DIFFUSE_PROPERTY_KEYS:
                    continue
                tex_pptr = getattr(tex_env, "m_Texture", None)
                if tex_pptr is None or not bool(tex_pptr):
                    continue
                # De-dup by path id
                pathid = int(getattr(tex_pptr, "m_PathID", 0))
                if pathid in seen_pathids:
                    continue
                seen_pathids.add(pathid)
                try:
                    tex = tex_pptr.deref_parse_as_object()
                    img = getattr(tex, "image", None)
                    if img is None:
                        continue
                    area = int(img.width) * int(img.height)
                    if area > best_area:
                        best_area = area
                        best_image = img
                except Exception:
                    continue

    return best_image  # type: ignore[no-any-return]

