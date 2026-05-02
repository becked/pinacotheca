"""ClutterSpawner decoder + procedural expander that produces PrefabPart
records for the existing renderer.

ClutterSpawner is the third clutter MonoBehaviour Old World uses, sibling
to ClutterTransforms (explicit per-instance TRS list) and
TerrainClutterSplat (shader-driven mask, no mesh content). Unlike
ClutterTransforms, the per-instance positions are *not* serialized — the
runtime generates them in `ClutterSpawnerBackgroundData.PopulateRenderData`
via a Halton 2D + RandomStruct procedure over a `gridBounds` rect, with
optional `textureMask` density redistribution.

Affects 11 resource prefabs that produce no `RESOURCE_3D_*.png` without
this module: Iron, Gem, Gold, Silver, Wheat, Barley, Sorghum, Honey,
Lavender, Olive, Wine. See GitHub issue #2.

# Deviations from the runtime

The expander faithfully ports the geometric layout but skips three pieces
that don't matter for offline standalone resource renders:

  - `useWorldRandomness` world-position hash: the host GO is at world
    origin, so the hash term is constant. We use `randomSeed` raw,
    yielding stable cross-run renders without per-tile variation.
  - `TerrainPhysics.GetGlobalTerrainHeightData` cull + heightmap snap:
    no global terrain is loaded offline, so the runtime branch returns
    false and both effects are no-ops.
  - `textureSheetDimensions` UV remap and per-instance `minColor`/
    `maxColor` tinting: not surfaced through `bake_to_obj`, so all
    instances share the prefab's diffuse texture without sub-rect UVs
    or color jitter.

# World matrix composition

Mirrors `clutter_transforms.clutter_to_prefab_parts`:

    world_per_instance = parent_world @ matrix4x2 @ matrix4x

where `matrix4x2` is the random per-instance TRS (grid position + random
euler + random uniform scale) and `matrix4x` is the per-model TRS. The
runtime's `ClutterSpawnerBackgroundData.PopulateRenderData` line 220
composes the same product in the same order; the `localToWorld` field
captured in the BackgroundData equals `host.transform.localToWorldMatrix`
(set in `ClutterBase.InternalRegenerate:91`), which is `parent_world`
here.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from pinacotheca.clutter_culling import RandomStruct
from pinacotheca.clutter_transforms import (
    ObjectReaderAsPPtr,
    PPtr,
    _adapt_pptr,
    _resolve_pptr_to_reader,
    _walk_prefab_with_world,
    euler_to_mat3,
    script_class,
)
from pinacotheca.cpu_texture import CPUTexture2D
from pinacotheca.halton import halton_sequence_2d
from pinacotheca.prefab import PrefabPart, _components_of, _decode_texture

logger = logging.getLogger(__name__)


# ============================================================
# Parsed dataclasses
# ============================================================


@dataclass(frozen=True)
class SpawnerModel:
    """One entry in `ClutterSpawner.models`. Mirrors the C# nested
    `ClutterSpawner.Model` class, dropping fields not consumed by the
    expander (the debug/runtime-only ones: `initialized`, `finalInstances`,
    `staticBatch`, `indirectInstance`, `materialLayer`, `sortingOffset`,
    `expandRenderingBounds`, `proceduralDamage`).
    """

    mesh: PPtr
    material: PPtr
    # Per-model TRS (matrix4x in PopulateRenderData line 149).
    position: tuple[float, float, float]
    rotation_euler: tuple[float, float, float]
    scale: tuple[float, float, float]
    # Layout.
    num_instances: int
    instance_radius: float
    grid_bounds: tuple[float, float, float, float]  # x, y, width, height (Unity Rect)
    texture_mask: PPtr
    texture_channel: int
    clutter_type: int
    # Randomness.
    use_world_randomness: bool
    random_seed: int
    min_position: tuple[float, float, float]
    max_position: tuple[float, float, float]
    min_rotation: tuple[float, float, float]
    max_rotation: tuple[float, float, float]
    min_scale: float
    max_scale: float
    # Debug.
    hide: bool


@dataclass(frozen=True)
class ParsedClutterSpawner:
    use_heightmap: bool
    hide_instances: bool
    models: tuple[SpawnerModel, ...]


def _adapt_v3(d: dict[str, Any]) -> tuple[float, float, float]:
    return float(d["x"]), float(d["y"]), float(d["z"])


def _adapt_rect(d: dict[str, Any]) -> tuple[float, float, float, float]:
    return float(d["x"]), float(d["y"]), float(d["width"]), float(d["height"])


def parse_clutter_spawner(env: Any, obj: Any) -> ParsedClutterSpawner:
    """Decode a ClutterSpawner MonoBehaviour into the dataclass shape via
    typetree. Layout drift will fail loudly with a `KeyError` on a renamed
    or removed field — same fail-loud stance as the other typetree-backed
    parsers."""
    from pinacotheca.typetree import decode_monobehaviour

    d = decode_monobehaviour(env, obj, "ClutterSpawner")
    models: list[SpawnerModel] = []
    for md in d["models"]:
        models.append(
            SpawnerModel(
                mesh=_adapt_pptr(md["mesh"]),
                material=_adapt_pptr(md["material"]),
                position=_adapt_v3(md["position"]),
                rotation_euler=_adapt_v3(md["rotation"]),
                scale=_adapt_v3(md["scale"]),
                num_instances=int(md["numInstances"]),
                instance_radius=float(md["instanceRadius"]),
                grid_bounds=_adapt_rect(md["gridBounds"]),
                texture_mask=_adapt_pptr(md["textureMask"]),
                texture_channel=int(md["textureChannel"]),
                clutter_type=int(md["clutterType"]),
                use_world_randomness=bool(md["useWorldRandomness"]),
                random_seed=int(md["randomSeed"]),
                min_position=_adapt_v3(md["minPosition"]),
                max_position=_adapt_v3(md["maxPosition"]),
                min_rotation=_adapt_v3(md["minRotation"]),
                max_rotation=_adapt_v3(md["maxRotation"]),
                min_scale=float(md["minScale"]),
                max_scale=float(md["maxScale"]),
                hide=bool(md["hide"]),
            )
        )
    return ParsedClutterSpawner(
        use_heightmap=bool(d["useHeightmap"]),
        hide_instances=bool(d["hideInstances"]),
        models=tuple(models),
    )


# ============================================================
# Walker
# ============================================================


def find_clutter_spawners_in_prefab(
    root_go: Any,
) -> list[tuple[ParsedClutterSpawner, NDArray[np.float64]]]:
    """Descend the prefab tree, find every ClutterSpawner MonoBehaviour,
    and pair each parsed instance with the world matrix of its hosting GO.

    Mirrors `clutter_transforms.find_clutter_transforms_in_prefab` —
    matches by script class name (resilient to GO-name variation across
    prefabs: e.g. Wheat_Instances hosts on its root, Lavender hosts on a
    child `LavenderClutter` GO).
    """
    found: list[tuple[ParsedClutterSpawner, NDArray[np.float64]]] = []
    for go, world in _walk_prefab_with_world(root_go):
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
            if cls != "ClutterSpawner":
                continue
            try:
                parsed = parse_clutter_spawner(r.assets_file.parent, r)
            except Exception as e:
                logger.warning("ClutterSpawner decode failed: %s", e)
                continue
            found.append((parsed, world))
    return found


# ============================================================
# Procedural expander
# ============================================================


def _trs_matrix(
    pos: tuple[float, float, float],
    euler_deg: tuple[float, float, float],
    scale: tuple[float, float, float],
) -> NDArray[np.float64]:
    """Build a 4x4 TRS matrix from Unity-style components. Equivalent to
    `Matrix4x4.TRS` — the rotation uses the same ZXY-intrinsic Euler
    convention as `clutter_transforms.euler_to_mat3`."""
    m = np.eye(4, dtype=np.float64)
    r = euler_to_mat3(*euler_deg)
    sx, sy, sz = scale
    m[:3, :3] = r * np.array([sx, sy, sz], dtype=np.float64)
    m[0, 3] = pos[0]
    m[1, 3] = pos[1]
    m[2, 3] = pos[2]
    return m


def clutter_spawner_to_prefab_parts(
    env: Any,
    parsed: ParsedClutterSpawner,
    parent_world: NDArray[np.float64],
) -> list[PrefabPart]:
    """Expand a parsed ClutterSpawner into one PrefabPart per (model, instance).

    Replicates `ClutterSpawnerBackgroundData.PopulateRenderData` minus
    the deviations documented at module top. The resulting world matrix
    per instance is `parent_world @ matrix4x2 @ matrix4x`, identical in
    composition to the runtime's stored InstanceMatrices.

    Returns an empty list if `hide_instances` is set or if every model
    is individually hidden / has zero instances.
    """
    if parsed.hide_instances:
        return []

    parts: list[PrefabPart] = []
    for model in parsed.models:
        parts.extend(_expand_model(env, model, parent_world))
    return parts


def _expand_model(
    env: Any,
    model: SpawnerModel,
    parent_world: NDArray[np.float64],
) -> list[PrefabPart]:
    if model.hide or model.num_instances <= 0:
        return []

    mesh_reader = _resolve_pptr_to_reader(env, model.mesh)
    if mesh_reader is None or mesh_reader.type.name != "Mesh":
        logger.debug("ClutterSpawner mesh PPtr did not resolve to a Mesh: %s", model.mesh)
        return []

    materials: list[Any] = []
    mat_reader = _resolve_pptr_to_reader(env, model.material)
    if mat_reader is not None and mat_reader.type.name == "Material":
        materials.append(ObjectReaderAsPPtr(mat_reader))

    mask = _resolve_texture_mask(env, model.texture_mask)

    matrix4x = _trs_matrix(model.position, model.rotation_euler, model.scale)

    rng = RandomStruct(model.random_seed)

    # See PopulateRenderData lines 152-155 — these scale the per-instance
    # random offset so it's roughly one grid-cell of jitter, then the
    # vector2 inverts the gridBounds dimensions to convert that offset
    # back into normalized UV space for the textureMask query.
    sqrt_n = math.sqrt(model.num_instances)
    grid_x, grid_y, grid_w, grid_h = model.grid_bounds
    cell_w = grid_w / max(sqrt_n - 1.0, 1.0)
    cell_h = grid_h / max(sqrt_n - 1.0, 1.0)
    inv_grid_w = 1.0 / max(grid_w, 1e-6)
    inv_grid_h = 1.0 / max(grid_h, 1e-6)

    # Halton index offset — runtime uses `i + num` where num is the seed
    # (post-world-randomness mask). We use random_seed directly per the
    # useWorldRandomness deviation noted at module top.
    halton_offset = model.random_seed

    instance_spheres: list[tuple[float, float, float]] = []  # (x, z, radius)
    out: list[PrefabPart] = []
    mesh_obj = ObjectReaderAsPPtr(mesh_reader)

    for i in range(model.num_instances):
        # Halton-sequence base position in normalized [0, 1)^2.
        x, y = halton_sequence_2d(i + halton_offset)

        # Per-instance random offset (note: y stays in world space, x and
        # z are scaled by cell width/height).
        off = (
            rng.range_float(model.min_position[0], model.max_position[0]) * cell_w,
            rng.range_float(model.min_position[1], model.max_position[1]),
            rng.range_float(model.min_position[2], model.max_position[2]) * cell_h,
        )
        euler = (
            rng.range_float(model.min_rotation[0], model.max_rotation[0]),
            rng.range_float(model.min_rotation[1], model.max_rotation[1]),
            rng.range_float(model.min_rotation[2], model.max_rotation[2]),
        )
        scale_factor = rng.range_float(model.min_scale, model.max_scale)
        # Color lerp consumes a NextFloat() — must be drawn even though
        # we don't use the result, to keep the random sequence aligned
        # with the runtime.
        rng.next_float()

        x += off[0] * inv_grid_w
        y += off[2] * inv_grid_h

        if mask is not None:
            x, y = mask.get_inverse_density(x, y, model.texture_channel)

        # World-space position before parent_world (i.e. local to the
        # spawner host's coordinate frame). Z gets the v-axis offset to
        # match the runtime's grid → world remap.
        local_pos = (
            grid_x + x * grid_w,
            off[1],
            grid_y + y * grid_h,
        )
        matrix4x2 = _trs_matrix(local_pos, euler, (scale_factor, scale_factor, scale_factor))

        world_matrix = parent_world @ matrix4x2 @ matrix4x

        if model.instance_radius > 0.0:
            wx = float(world_matrix[0, 3])
            wz = float(world_matrix[2, 3])
            r = model.instance_radius
            collided = False
            for sx, sz, sr in instance_spheres:
                dx = sx - wx
                dz = sz - wz
                rsum = sr + r
                if dx * dx + dz * dz <= rsum * rsum:
                    collided = True
                    break
            if collided:
                continue
            instance_spheres.append((wx, wz, r))

        out.append(
            PrefabPart(
                mesh_obj=mesh_obj,
                world_matrix=world_matrix,
                materials=materials,
            )
        )

    return out


def _resolve_texture_mask(env: Any, pptr: PPtr) -> CPUTexture2D | None:
    """Resolve a textureMask PPtr to a CPUTexture2D, or None for null /
    decode failure. Reuses `prefab._decode_texture` so the BC6H fallback
    and other quirks of the standard pipeline apply here too."""
    if pptr.is_null():
        return None
    reader = _resolve_pptr_to_reader(env, pptr)
    if reader is None or reader.type.name != "Texture2D":
        logger.debug("ClutterSpawner textureMask did not resolve to a Texture2D: %s", pptr)
        return None
    try:
        tex = reader.parse_as_object()
    except Exception as e:
        logger.debug("textureMask parse failed: %s", e)
        return None
    img = _decode_texture(tex)
    if img is None:
        return None
    return CPUTexture2D(img)
