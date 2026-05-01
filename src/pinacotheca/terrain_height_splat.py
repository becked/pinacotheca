"""TerrainHeightSplat finder + offline CPU tessellation/displacement.

The game's mountains, volcanos, and hills ship as **flat Quad meshes**.
Their 3D shape is generated at runtime by a Unity vertex shader that
tessellates the Quad and pushes vertex Y based on a heightmap texture.
The relevant `TerrainHeightSplat` MonoBehaviour is hand-parsed in
``pvt_splats.parse_height_splat`` (already present for drift detection).

This module adds:

1. A finder (``find_height_splats_in_prefab``) that returns one
   ``HeightSplatPart`` per ``TerrainHeightSplat`` MonoBehaviour on the
   prefab tree, paired with the host GameObject's MeshFilter mesh + world
   matrix.

2. A CPU tessellator (``tessellate_displaced_obj``) that takes a Quad
   mesh and a height splat, subdivides into an N×N grid, samples the
   heightmap at each sub-vertex's UV, displaces Y, recomputes normals
   from the displaced surface, and emits an OBJ string consumable by
   ``renderer.render_mesh_to_image``.

Empirical findings (verified against game prefabs, see commit message):

* On every base-game mountain/volcano/hill prefab, ``rgb_heightmap`` is
  null and only ``heightmap`` is set. The C# field tooltips describe
  ``rgb_heightmap`` as the height source and ``heightmap`` as the
  alphamask, but the data flips that — ``heightmap`` IS the height
  source. We sample its R channel directly. Empirically R=G=B (grayscale
  encoding), so any of the three would do.
* ``rgb_heightmap_middle`` is 0.0 on every base-game prefab → no offset.
* ``alphamap_scale_bias`` is (1.0, 0.0) on every base-game prefab →
  identity UV transform. We honor it as ``uv * scale + bias`` (uniform
  scale, uniform bias) for forward compatibility.
* ``override_world_uv`` is False on every base-game prefab → sample at
  mesh UV, not world XZ.
* Per-prefab intensities: TileMountain=4.0, TileVolcano_1=6.0,
  HillsTemperate=3.0, TileOcean (CoastFlattener)=-4.0.

The Quad is typically the 4-vertex Unity built-in. We tessellate by
bilerping mesh-local position + UV across an N×N grid, then transform
to world space via the host GameObject's TRS. Output OBJ is in our
right-handed convention (X negated, faces re-wound) — same conventions
``bake_to_obj`` uses, so the renderer treats it identically.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from pinacotheca.clutter_transforms import (
    _resolve_pptr_to_reader,
    _walk_prefab_with_world,
    script_class,
)
from pinacotheca.prefab import (
    _component_by_type,
    _components_of,
    _decode_texture,
)
from pinacotheca.pvt_splats import (
    HeightSplatFields,
    parse_height_splat,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HeightSplatPart:
    """One TerrainHeightSplat MonoBehaviour found inside a prefab tree.

    Same shape as ``PvtPlanePart`` so callers can route both kinds of
    splat through similar code paths. ``mesh_obj`` is the host
    GameObject's MeshFilter mesh PPtr (typically a Unity built-in Quad);
    ``world_matrix`` is the host's accumulated TRS.
    """

    parsed: HeightSplatFields
    mesh_obj: Any  # MeshFilter m_Mesh PPtr — UnityPy native form
    world_matrix: NDArray[np.float64]
    host_go_name: str


def find_height_splats_in_prefab(root_go: Any) -> list[HeightSplatPart]:
    """Descend the prefab tree, find every ``TerrainHeightSplat``, pair
    each with its host GameObject's MeshFilter mesh + world matrix.

    Mirrors ``pvt_splats.find_pvt_splats_in_prefab``. Hosts without a
    MeshFilter or with a null mesh are logged and skipped — those are
    height splats authored as data-only nodes that the shader applies to
    a sibling mesh (we haven't seen this in the base game).
    """
    found: list[HeightSplatPart] = []
    for go, world in _walk_prefab_with_world(root_go):
        height_parsed: HeightSplatFields | None = None
        for pptr in _components_of(go):
            try:
                r = pptr.deref()
                if r.type.name != "MonoBehaviour":
                    continue
            except Exception:
                continue
            try:
                cls = script_class(r)
            except Exception:
                continue
            if cls != "TerrainHeightSplat":
                continue
            try:
                raw = r.get_raw_data()
            except Exception as e:
                logger.warning("TerrainHeightSplat get_raw_data failed: %s", e)
                continue
            try:
                height_parsed = parse_height_splat(raw)
            except ValueError as e:
                logger.warning("TerrainHeightSplat parse failed: %s", e)
                continue
            break  # one TerrainHeightSplat per GameObject

        if height_parsed is None:
            continue

        mf = _component_by_type(go, "MeshFilter")
        if mf is None:
            logger.warning(
                "TerrainHeightSplat on %r has no MeshFilter sibling; skipping",
                getattr(go, "m_Name", "?"),
            )
            continue
        mf_mesh = getattr(mf, "m_Mesh", None)
        if mf_mesh is None or not bool(mf_mesh):
            logger.warning(
                "TerrainHeightSplat on %r has MeshFilter with null mesh; skipping",
                getattr(go, "m_Name", "?"),
            )
            continue

        found.append(
            HeightSplatPart(
                parsed=height_parsed,
                mesh_obj=mf_mesh,
                world_matrix=world.copy(),
                host_go_name=str(getattr(go, "m_Name", "?")),
            )
        )
    return found


def _resolve_heightmap_image(env: Any, height_part: HeightSplatPart) -> Image.Image | None:
    """Decode the height splat's heightmap texture to a PIL grayscale image.

    Prefers ``heightmap`` (which on every base-game prefab is the actual
    height source — see module docstring). Falls back to ``rgb_heightmap``
    for forward compatibility with prefabs that may use the C#-documented
    field semantics. Returns ``None`` when neither resolves.
    """
    p = height_part.parsed
    for field_name, pptr in (("heightmap", p.heightmap), ("rgb_heightmap", p.rgb_heightmap)):
        if pptr.is_null():
            continue
        reader = _resolve_pptr_to_reader(env, pptr)
        if reader is None:
            logger.debug(
                "Height splat %r %s PPtr did not resolve",
                height_part.host_go_name,
                field_name,
            )
            continue
        try:
            tex = reader.parse_as_object()
        except Exception as e:
            logger.warning(
                "Height splat %r %s parse_as_object failed: %s",
                height_part.host_go_name,
                field_name,
                e,
            )
            continue
        img = _decode_texture(tex)
        if img is None:
            logger.warning(
                "Height splat %r %s texture decode returned None",
                height_part.host_go_name,
                field_name,
            )
            continue
        return img.convert("RGBA")

    logger.warning(
        "Height splat %r has no resolvable heightmap (both PPtrs null/unresolvable)",
        height_part.host_go_name,
    )
    return None


def _sample_heightmap_bilinear(
    heightmap_array: NDArray[np.float32],
    u: NDArray[np.float64],
    v: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Bilinear-sample R channel at fractional UV coords. Wraps to clamp.

    Inputs ``u``, ``v`` are arrays of shape (..., ) with values in [0, 1].
    Returns sampled values in [0, 1].
    """
    h, w = heightmap_array.shape[:2]
    fx = np.clip(u, 0.0, 1.0) * (w - 1)
    fy = np.clip(1.0 - v, 0.0, 1.0) * (h - 1)  # Unity UVs are bottom-up; image rows are top-down
    x0 = np.floor(fx).astype(np.int64)
    y0 = np.floor(fy).astype(np.int64)
    x1 = np.clip(x0 + 1, 0, w - 1)
    y1 = np.clip(y0 + 1, 0, h - 1)
    sx = fx - x0
    sy = fy - y0
    # Sample R channel
    r00 = heightmap_array[y0, x0]
    r10 = heightmap_array[y0, x1]
    r01 = heightmap_array[y1, x0]
    r11 = heightmap_array[y1, x1]
    out = (r00 * (1 - sx) + r10 * sx) * (1 - sy) + (r01 * (1 - sx) + r11 * sx) * sy
    return np.asarray(out, dtype=np.float64)


def _read_quad_mesh(mesh_pptr: Any) -> tuple[NDArray[np.float64], NDArray[np.float64]] | None:
    """Read a Quad mesh's vertices + UVs. Returns ``(verts, uvs)`` arrays
    of shape ``(N, 3)`` and ``(N, 2)`` respectively.

    Returns ``None`` if the mesh can't be read or has no UVs (we need the
    UV space to sample the heightmap; world-XZ fallback would require
    ``override_world_uv`` to be true, which it isn't on any base-game
    prefab).
    """
    from UnityPy.helpers.MeshHelper import MeshHandler

    try:
        mesh = mesh_pptr.deref_parse_as_object()
        handler = MeshHandler(mesh)
        handler.process()  # type: ignore[no-untyped-call]
    except Exception as e:
        logger.warning("Quad mesh read failed: %s", e)
        return None

    if not handler.m_Vertices or not handler.m_UV0:
        logger.warning("Quad mesh has no vertices or no UV0; cannot tessellate")
        return None

    verts = np.asarray(handler.m_Vertices, dtype=np.float64)
    uvs = np.asarray(handler.m_UV0, dtype=np.float64)
    return verts, uvs


def tessellate_displaced_obj(
    env: Any,
    plane_mesh_pptr: Any,
    plane_world_matrix: NDArray[np.float64],
    height_part: HeightSplatPart,
    *,
    subdivisions: int = 64,
    pre_rotation_y_deg: float = 180.0,
) -> str | None:
    """Tessellate a flat Quad to ``subdivisions``×``subdivisions``, displace
    world Y from the height splat's heightmap, return an OBJ string.

    Strategy:

    1. Read the source Quad's 4 corner positions + UVs (in mesh-local
       space). The Unity built-in Quad has vertices in the XY plane
       (Z≈0); the world matrix on terrain prefabs rotates this to lie
       flat in world XZ (Y up).
    2. Build an (N+1)×(N+1) parametric grid in [0, 1]² and bilerp both
       mesh-local position and UV across the four corners.
    3. Apply the host's world matrix (with optional Y pre-rotation) to
       transform grid positions into world space — they now sit on the
       world XZ plane with world Y ≈ 0.
    4. Sample the heightmap at the bilerped UV (scaled+biased per the
       parsed ``alphamap_scale_bias``) and *add* the displacement to
       world Y. Doing this in world space rather than mesh-local Y is
       essential because the world matrix's 90° rotation maps mesh-local
       Z → world -Y; displacing mesh-local Y would push the geometry
       sideways instead of up.
    5. Recompute per-vertex normals from the displaced grid via central
       differences (numpy ``gradient``). Mirror the normals if the
       world matrix has negative determinant (Old World mountain
       matrices flip parity).
    6. Emit OBJ with our right-handed convention (X negated, faces
       wound to keep displaced peaks facing the camera).

    ``pre_rotation_y_deg`` (default 180°) matches ``bake_to_obj``'s
    convention for buildings: rotate the prefab 180° around Y so its
    authored -Z front face our renderer's +Z view direction.

    Returns ``None`` on irrecoverable failure (mesh unreadable, heightmap
    unresolvable). The caller is expected to fall back to a flat-shaded
    render in that case.
    """
    quad = _read_quad_mesh(plane_mesh_pptr)
    if quad is None:
        return None
    verts_local, uvs_local = quad

    heightmap_img = _resolve_heightmap_image(env, height_part)
    if heightmap_img is None:
        return None
    hm_array = np.asarray(heightmap_img, dtype=np.float32)[..., 0] / 255.0  # R channel, normalized

    # Find the four UV corners (00, 10, 01, 11) and their mesh-local
    # positions, so we can bilerp both consistently. Sort the source
    # vertices by UV to identify which mesh-local position corresponds to
    # which UV corner — robust to vertex order across different built-in
    # Unity Quad meshes.
    if verts_local.shape[0] < 4 or uvs_local.shape[0] < 4:
        logger.warning(
            "Plane mesh has fewer than 4 vertices/UVs (%d/%d); cannot tessellate",
            verts_local.shape[0],
            uvs_local.shape[0],
        )
        return None
    u_min, v_min = uvs_local.min(axis=0)
    u_max, v_max = uvs_local.max(axis=0)

    def _vertex_for_uv(target_u: float, target_v: float) -> NDArray[np.float64]:
        """Return the mesh-local vertex closest to the requested (u, v)."""
        d = (uvs_local[:, 0] - target_u) ** 2 + (uvs_local[:, 1] - target_v) ** 2
        return np.asarray(verts_local[int(np.argmin(d))], dtype=np.float64)

    p00 = _vertex_for_uv(u_min, v_min)
    p10 = _vertex_for_uv(u_max, v_min)
    p01 = _vertex_for_uv(u_min, v_max)
    p11 = _vertex_for_uv(u_max, v_max)

    n = max(2, int(subdivisions))
    t = np.linspace(0.0, 1.0, n + 1, dtype=np.float64)
    grid_t, grid_s = np.meshgrid(t, t, indexing="ij")  # shape (n+1, n+1)
    s = grid_s[..., None]  # (n+1, n+1, 1) for broadcast against (3,)
    tt = grid_t[..., None]

    # Bilerp mesh-local positions across the parametric grid. Output
    # shape: (n+1, n+1, 3).
    pos_local = (1 - s) * (1 - tt) * p00 + s * (1 - tt) * p10 + (1 - s) * tt * p01 + s * tt * p11

    # Bilerp UVs identically.
    uv_u = u_min + grid_s * (u_max - u_min)
    uv_v = v_min + grid_t * (v_max - v_min)

    # Apply optional Y pre-rotation, then the host's world matrix. We do
    # this BEFORE displacement so the Y axis we displace along is world-up.
    if pre_rotation_y_deg != 0.0:
        theta = float(np.radians(pre_rotation_y_deg))
        c, s_ = float(np.cos(theta)), float(np.sin(theta))
        pre_rot = np.array(
            [
                [c, 0.0, s_, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [-s_, 0.0, c, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )
        m = pre_rot @ plane_world_matrix
    else:
        m = plane_world_matrix
    flat_local = pos_local.reshape(-1, 3)
    flat_h = np.concatenate(
        [flat_local, np.ones((flat_local.shape[0], 1), dtype=np.float64)], axis=1
    )
    world_h = flat_h @ m.T
    world_xyz = world_h[:, :3].copy()

    # Displace world Y by sampled heightmap × intensity. ``alphamap_scale_bias``
    # is honored as uniform (scale, bias) — base-game default is (1, 0)
    # so the transform is a no-op, but plumbed for forward compat.
    p = height_part.parsed
    scale, bias = p.alphamap_scale_bias
    uv_alpha_u = uv_u.ravel() * scale + bias
    uv_alpha_v = uv_v.ravel() * scale + bias
    height_value = _sample_heightmap_bilinear(hm_array, uv_alpha_u, uv_alpha_v)
    world_xyz[:, 1] += (height_value - p.rgb_heightmap_middle) * p.intensity

    # Compute per-vertex normals via central differences on the grid.
    verts_grid = world_xyz.reshape(n + 1, n + 1, 3)
    # dPos/du (axis=1 in grid) and dPos/dv (axis=0 in grid). Cross order
    # is (dv × du) so flat sections produce world-up (+Y) normals; with
    # the displaced grid this yields outward-facing normals on the peaks.
    du = np.gradient(verts_grid, axis=1)
    dv = np.gradient(verts_grid, axis=0)
    normals_grid = np.cross(dv, du)
    norm_lengths = np.linalg.norm(normals_grid, axis=2, keepdims=True)
    norm_lengths[norm_lengths == 0.0] = 1.0
    normals_grid = normals_grid / norm_lengths
    # World-matrix det < 0 → mirrored. Mirroring inverts cross-product
    # direction; flip normals so they still point outward.
    if float(np.linalg.det(m[:3, :3])) < 0.0:
        normals_grid = -normals_grid
    normals_world = normals_grid.reshape(-1, 3)

    # Right-handed OBJ convention: negate X on positions and normals.
    # Triangles re-wound below to compensate for the parity flip.
    sb: list[str] = []
    sb.append("g terrain_displaced\n")
    for vx, vy, vz in world_xyz:
        sb.append(f"v {-vx:.9G} {vy:.9G} {vz:.9G}\n")
    uv_flat = np.stack([uv_u.ravel(), uv_v.ravel()], axis=1)
    for u, v in uv_flat:
        sb.append(f"vt {u:.9G} {v:.9G}\n")
    for nx, ny, nz in normals_world:
        sb.append(f"vn {-nx:.9G} {ny:.9G} {nz:.9G}\n")

    # Tangents: with X negated and the axis-aligned UV grid, the world-X
    # tangent maps to local-U (sign-flipped). Emit a uniform tangent so
    # the shader's normal-mapping path stays well-defined; without normal
    # maps in this material this is harmless.
    for _ in range(world_xyz.shape[0]):
        sb.append("vtg 1 0 0 1\n")

    # Faces: two triangles per cell. Vertices are 1-indexed in OBJ.
    sb.append("g terrain_displaced_sub0\n")
    for j in range(n):
        for i in range(n):
            v00 = j * (n + 1) + i + 1
            v10 = j * (n + 1) + (i + 1) + 1
            v01 = (j + 1) * (n + 1) + i + 1
            v11 = (j + 1) * (n + 1) + (i + 1) + 1
            # X-flip reverses winding; emit triangles so normals face the
            # camera (i.e. "up" at the peak). Trial-derived order below.
            sb.append(
                f"f {v00}/{v00}/{v00} {v10}/{v10}/{v10} {v11}/{v11}/{v11}\n"
                f"f {v00}/{v00}/{v00} {v11}/{v11}/{v11} {v01}/{v01}/{v01}\n"
            )
    return "".join(sb)
