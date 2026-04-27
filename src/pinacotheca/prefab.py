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


def bake_to_obj(parts: list[PrefabPart], *, pre_rotation_y_deg: float = 0.0) -> str:
    """
    Bake parts into a single OBJ string in OpenGL right-handed space.

    Applies each part's world matrix to its vertices (inverse-transpose
    for normals), then performs the Unity → right-handed conversion:
    negate X on positions and normals, reverse triangle winding. The
    result is consumable by `renderer.parse_obj()` directly.

    Parts with no usable mesh data are skipped silently.

    Args:
        pre_rotation_y_deg: optional Y-axis rotation (in degrees) applied
            to every part's world matrix before baking. Used by the
            improvement extractor to flip buildings 180° so their authored
            front face (Unity -Z) appears on the OBJ +Z side our renderer
            views. Y rotation is a proper rotation (det = +1), so the
            winding-flip logic below is unaffected. Default 0° preserves
            historical behavior for non-extractor callers.
    """
    from UnityPy.helpers.MeshHelper import MeshHandler

    # Build the optional Y-rotation pre-multiplier once. Identity when no
    # rotation is requested so the inner loop is unchanged for that path.
    if pre_rotation_y_deg != 0.0:
        theta = float(np.radians(pre_rotation_y_deg))
        c, s = float(np.cos(theta)), float(np.sin(theta))
        pre_rot = np.array(
            [
                [c, 0.0, s, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [-s, 0.0, c, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )
    else:
        pre_rot = None

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

        m = part.world_matrix if pre_rot is None else pre_rot @ part.world_matrix
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


# Material name patterns identifying Old World's terrain splat-shader meshes.
# These are heightmap/alphamap/water surfaces blended at runtime by a custom
# shader; rendered with a standard textured-mesh shader they produce
# scrambled-hieroglyph artifacts where the alphamap encodes the building's
# own footprint. See docs/extracting-3d-buildings.md for the full story.
SPLAT_MATERIAL_PREFIXES: tuple[str, ...] = ("Splat",)
SPLAT_MATERIAL_EXACT: tuple[str, ...] = ("WaterNoFoam", "BathWater")

# Ground-stamp materials in priority order. SplatHeightDefault is the actual
# heightmap stamp the game uses to deform terrain UP around buildings; the
# others are co-located terrain texture/clutter splats and serve as fallbacks
# when no explicit height stamp exists. WATER_MATERIALS are visible water
# surfaces inside buildings (pools, cisterns), NOT ground stamps.
GROUND_HEIGHT_MATERIALS: tuple[str, ...] = ("SplatHeightDefault",)
GROUND_TERRAIN_MATERIALS: tuple[str, ...] = (
    "SplatClutterDefault",
    "SplatTextureDefaultPVT",
)
WATER_MATERIALS: tuple[str, ...] = ("WaterNoFoam", "BathWater")


def _is_splat_material_name(name: str) -> bool:
    if not name:
        return False
    if name in SPLAT_MATERIAL_EXACT:
        return True
    return any(name.startswith(p) for p in SPLAT_MATERIAL_PREFIXES)


def drop_splat_meshes(parts: list[PrefabPart]) -> list[PrefabPart]:
    """
    Filter PrefabParts whose first material is a splat-shader material.

    Catches `SplatHeightDefault`, `SplatTextureDefaultPVT`,
    `SplatClutterDefault`, and `WaterNoFoam` regardless of mesh name.
    Replaces the older mesh-name-only filter (`mesh.name == "Plane"`) which
    leaked custom-named splat meshes (`Quad`, `MarketSplat`, `HamletFloor`,
    `Maurya_PVT_Plane`, etc.).

    Defensive: if the filter would drop every part of a non-empty input,
    returns the original list unchanged. None of the curated assets trigger
    this today; it's cheap insurance against future asset shape changes.
    """
    kept: list[PrefabPart] = []
    for part in parts:
        is_splat = False
        for mat_pptr in part.materials:
            try:
                if not bool(mat_pptr):
                    continue
                mat = mat_pptr.deref_parse_as_object()
                mat_name = getattr(mat, "m_Name", "") or ""
            except Exception:
                continue
            if _is_splat_material_name(mat_name):
                is_splat = True
                break
        if not is_splat:
            kept.append(part)

    if parts and not kept:
        return parts
    return kept


def _primary_material_name(part: PrefabPart) -> str:
    """Return the part's first material name, or '' if unreadable."""
    for mat_pptr in part.materials:
        try:
            if not bool(mat_pptr):
                continue
            mat = mat_pptr.deref_parse_as_object()
            return str(getattr(mat, "m_Name", "") or "")
        except Exception:
            return ""
    return ""


def _world_y_max(part: PrefabPart) -> float | None:
    """Return the max world-space Y across a part's vertices, or None on failure."""
    from UnityPy.helpers.MeshHelper import MeshHandler

    try:
        mesh = part.mesh_obj.deref_parse_as_object()
        handler = MeshHandler(mesh)
        handler.process()  # type: ignore[no-untyped-call]
    except Exception:
        return None
    if handler.m_VertexCount <= 0 or not handler.m_Vertices:
        return None
    m = part.world_matrix
    y_max = -float("inf")
    for vx, vy, vz in handler.m_Vertices:
        wy = m[1, 0] * vx + m[1, 1] * vy + m[1, 2] * vz + m[1, 3]
        if wy > y_max:
            y_max = float(wy)
    return y_max if y_max != -float("inf") else None


def _world_y_min(part: PrefabPart) -> float | None:
    """Return the min world-space Y across a part's vertices, or None on failure."""
    from UnityPy.helpers.MeshHelper import MeshHandler

    try:
        mesh = part.mesh_obj.deref_parse_as_object()
        handler = MeshHandler(mesh)
        handler.process()  # type: ignore[no-untyped-call]
    except Exception:
        return None
    if handler.m_VertexCount <= 0 or not handler.m_Vertices:
        return None
    m = part.world_matrix
    y_min = float("inf")
    for vx, vy, vz in handler.m_Vertices:
        wy = m[1, 0] * vx + m[1, 1] * vy + m[1, 2] * vz + m[1, 3]
        if wy < y_min:
            y_min = float(wy)
    return y_min if y_min != float("inf") else None


def find_geometry_y_min(parts: list[PrefabPart]) -> float | None:
    """
    Return the minimum world Y across non-splat parts, or None.

    Used to sanity-check splat-plane Y in composite prefabs: if the
    splat plane sits well above the building's actual lowest geometry,
    it's likely on a terrace (e.g., Hanging_Garden) rather than at the
    true ground line, and the splat-Y should not be used as a plinth
    cut. Helper for that comparison.
    """
    y_mins: list[float] = []
    for part in parts:
        name = _primary_material_name(part)
        if _is_splat_material_name(name):
            continue
        y = _world_y_min(part)
        if y is not None:
            y_mins.append(y)
    return min(y_mins) if y_mins else None


def find_ground_y(parts: list[PrefabPart]) -> float | None:
    """
    Return the world Y of the prefab's terrain ground stamp, or None.

    Old World prefabs embed `Plane` GameObjects with `SplatHeightDefault`
    materials on Unity's `TerrainHeightSplat` layer. At runtime an
    orthographic camera bakes those into a global heightmap that deforms
    terrain UP to meet the building's footprint, hiding the plinth below.
    The Y of those planes is therefore the building's true ground line —
    the same value the game uses to know where to raise terrain to.

    We prefer `SplatHeightDefault` (the actual height stamp). If absent,
    we fall back to other ground splats (`SplatClutterDefault`,
    `SplatTextureDefaultPVT`) which sit at the same Y in practice.
    Water-surface materials (`WaterNoFoam`, `BathWater`) are excluded —
    they sit ABOVE the ground inside the architecture (bath water, ponds).

    Returns None when no ground splat is present (~22 of 56 single-piece
    improvements; mostly religious buildings and small rural assets).
    Callers should fall back to the density heuristic in that case.
    """
    height_ys: list[float] = []
    terrain_ys: list[float] = []
    for part in parts:
        name = _primary_material_name(part)
        if name in WATER_MATERIALS:
            continue
        if name in GROUND_HEIGHT_MATERIALS:
            y = _world_y_max(part)
            if y is not None:
                height_ys.append(y)
        elif name in GROUND_TERRAIN_MATERIALS:
            y = _world_y_max(part)
            if y is not None:
                terrain_ys.append(y)
    if height_ys:
        return max(height_ys)
    if terrain_ys:
        return max(terrain_ys)
    return None


def _parse_obj_vertices_and_faces(
    obj_str: str,
) -> tuple[list[tuple[float, float, float]], list[list[int]]]:
    """
    Lightweight OBJ parse used by `strip_plinth_from_obj`.

    Returns (vertices, faces_as_v_indices). Faces use 0-based vertex
    indices. UVs and normals are ignored — we only need vertex Y for the
    plinth-detection geometry and vertex indices to filter face lines.
    """
    vertices: list[tuple[float, float, float]] = []
    faces: list[list[int]] = []
    for line in obj_str.split("\n"):
        parts = line.strip().split()
        if not parts:
            continue
        if parts[0] == "v" and len(parts) >= 4:
            vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
        elif parts[0] == "f":
            face_idx: list[int] = []
            for token in parts[1:]:
                vidx_str = token.split("/")[0]
                if not vidx_str:
                    continue
                # OBJ is 1-indexed; convert to 0-indexed.
                face_idx.append(int(vidx_str) - 1)
            if len(face_idx) >= 3:
                faces.append(face_idx)
    return vertices, faces


def strip_plinth_from_obj(
    obj_str: str,
    *,
    cut_y_override: float | None = None,
    footprint_threshold: float = 0.80,
    extent_fraction: float = 0.05,
    density_threshold: float = 0.05,
    max_cut_fraction: float = 0.65,
    n_bins: int = 20,
) -> str:
    """
    Drop a baked-in plinth slab from an OBJ string.

    Some single-piece improvement meshes (Library, etc.) ship with a stone
    foundation slab as part of the mesh. Downstream consumers compositing
    our renders onto their own terrain hex layer end up with a visible
    double-floor effect. This function detects and removes the slab.

    Two paths to a cut height:

    **Path 1 — Explicit override** (``cut_y_override``):
        When the caller knows the ground line (e.g., from `find_ground_y`
        sampling the prefab's `SplatHeightDefault` plane), pass it here.
        Two safety guards: refuse if the override exceeds
        ``max_cut_fraction`` of the model's Y extent, and refuse if it
        would clamp ≥50% of vertices. Either guard falls through to the
        density heuristic below.

    **Path 2 — Density heuristic** (when no override or override rejected):
        1. **Detect**: bin verts by Y; if the bottom `extent_fraction`
           slice of Y verts covers ≥ `footprint_threshold` of the full
           XZ footprint, treat as plinth. Otherwise return unchanged.
        2. **Find slab top**: bin all verts into `n_bins` Y slices. Walk
           from the bottom; the first slice with ≥ `density_threshold`
           of total verts marks where the building proper begins. Cut at
           that slice's lower Y. Capped at `max_cut_fraction` of total
           extent so we never cut more than half the building. If no
           dense bin is found in that range, fall back to the detection
           cut (5%) — strips the slab's bottom face only, harmless.

    **Clamp + drop emission** (both paths share this):
        - Any vertex with Y < cut_y is clamped to Y = cut_y. This
          flattens slab side walls (which often span from y_min all
          the way up to the building base via long triangles) into a
          near-zero-thickness disc at cut_y. Triangle-drop alone is
          insufficient for these slabs because their side faces
          straddle the cut.
        - Any face whose three original vert Ys were all ≤ cut_y is
          dropped (slab top + bottom faces). The clamped disc has no
          surviving floor/ceiling, just the building geometry above.

    Two density thresholds are intentional: the slab's geometric extent
    (often 20–30% of total Y) is much larger than the detection window
    (5%), so the cut height must be discovered dynamically from vertex
    density rather than fixed at the detection knob. See Library's Y
    histogram in the per-ankh investigation: 12 verts at the slab's
    bottom (5%-of-Y bin), then a 30% empty Y region (slab interior),
    then 860 verts at the building's first floor (45%-of-Y bin) — that
    45% mark is the real slab top.

    Operates on Y-up world-space coords (Unity's native axis preserved by
    UnityPy's MeshExporter and by `bake_to_obj`).
    """
    vertices, faces = _parse_obj_vertices_and_faces(obj_str)
    if not vertices or not faces:
        return obj_str

    ys = [v[1] for v in vertices]
    y_min = min(ys)
    y_max = max(ys)
    extent = y_max - y_min
    if extent <= 0:
        return obj_str

    cut_y: float | None = None

    # ─── Path 1: explicit override (typically find_ground_y splat-Y) ────
    if cut_y_override is not None:
        max_cut_y = y_min + max_cut_fraction * extent
        if cut_y_override <= max_cut_y:
            verts_below = sum(1 for v in vertices if v[1] < cut_y_override)
            if verts_below * 2 < len(vertices):
                cut_y = cut_y_override

    # ─── Path 2: density heuristic ──────────────────────────────────────
    if cut_y is None:
        detect_cut = y_min + extent_fraction * extent

        xs_all = [v[0] for v in vertices]
        zs_all = [v[2] for v in vertices]
        full_area = (max(xs_all) - min(xs_all)) * (max(zs_all) - min(zs_all))
        if full_area <= 0:
            return obj_str

        bottom_verts = [v for v in vertices if v[1] <= detect_cut]
        if not bottom_verts:
            return obj_str
        bxs = [v[0] for v in bottom_verts]
        bzs = [v[2] for v in bottom_verts]
        bottom_area = (max(bxs) - min(bxs)) * (max(bzs) - min(bzs))

        if bottom_area / full_area < footprint_threshold:
            return obj_str

        # Plinth detected — find the slab's top via vertex density.
        bin_h = extent / n_bins
        bins = [0] * n_bins
        for v in vertices:
            idx = min(int((v[1] - y_min) / bin_h), n_bins - 1)
            bins[idx] += 1
        threshold_count = max(1, int(len(vertices) * density_threshold))
        max_bin_idx = int(n_bins * max_cut_fraction)
        cut_y = detect_cut  # fallback if no dense bin found below the cap
        for i in range(min(max_bin_idx + 1, n_bins)):
            if bins[i] >= threshold_count:
                cut_y = y_min + i * bin_h
                break

    # ─── Clamp + drop emission ──────────────────────────────────────────
    out_lines: list[str] = []
    for line in obj_str.split("\n"):
        stripped = line.strip().split()
        if stripped:
            if stripped[0] == "v" and len(stripped) >= 4:
                # Clamp Y to cut_y for sub-cut verts; preserves topology.
                vy = float(stripped[2])
                if vy < cut_y:
                    out_lines.append(
                        f"v {float(stripped[1]):.9G} {cut_y:.9G} {float(stripped[3]):.9G}"
                    )
                    continue
            elif stripped[0] == "f":
                face_idx: list[int] = []
                for token in stripped[1:]:
                    vidx_str = token.split("/")[0]
                    if vidx_str:
                        face_idx.append(int(vidx_str) - 1)
                if len(face_idx) >= 3 and all(
                    vertices[i][1] <= cut_y for i in face_idx if 0 <= i < len(vertices)
                ):
                    continue
        out_lines.append(line)
    return "\n".join(out_lines)
