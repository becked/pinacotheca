"""ClutterTransforms decoder + prefab-tree walker that produces PrefabPart
records for the existing renderer.

ClutterTransforms is a Unity MonoBehaviour Old World uses to instance many
copies of a small set of meshes (capital buildings, urban tile flavor,
etc.). Bundles ship without inline TypeTrees, so we route MonoBehaviour
decode through `pinacotheca.typetree` (TypeTreeGeneratorAPI reads
Assembly-CSharp.dll on demand and feeds UnityPy's `read_typetree`).

For the rendering math see docs/runtime-composed-cities.md.
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from pinacotheca.prefab import (
    PrefabPart,
    _component_by_type,
    _components_of,
    trs_matrix,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PPtr:
    """A Unity PPtr: int32 m_FileID + int64 m_PathID."""

    file_id: int
    path_id: int

    def is_null(self) -> bool:
        return self.file_id == 0 and self.path_id == 0


class ObjectReaderAsPPtr:
    """Adapter that lets a UnityPy ObjectReader stand in for a PPtr.

    `bake_to_obj` calls `mesh.deref_parse_as_object()` on the mesh ref of
    each PrefabPart; `find_diffuse_for_prefab` does the same on each
    material ref. When we resolve a hand-parsed PPtr to an ObjectReader
    via path-id lookup, wrapping the reader with this adapter lets it slot
    into both shapes without touching the existing pipeline.
    """

    __slots__ = ("_reader",)

    def __init__(self, reader: Any) -> None:
        self._reader = reader

    def deref_parse_as_object(self) -> Any:
        return self._reader.parse_as_object()

    def __bool__(self) -> bool:
        return True


def find_object_by_path_id(env: Any, path_id: int) -> Any | None:
    """Find an Object by pathID, scoped to resources.assets only.

    PathIDs are unique per-asset-file, not globally — and the meshes
    referenced from a capital's ClutterTransforms live in resources.assets,
    not globalgamemanagers.assets where the env may have script classes
    loaded under colliding pathIDs.
    """
    for fname, f in env.files.items():
        if "resources.assets" in fname and not fname.endswith(".resS"):
            target = getattr(f, "objects", {}).get(path_id)
            if target is not None:
                return target
    return None


def script_class(reader: Any) -> str:
    """Return the script class name of a MonoBehaviour ObjectReader.

    Reads the m_Script PPtr from the raw binary at offset 16 (after
    12-byte m_GameObject + 4-byte aligned m_Enabled) and resolves it.
    Returns a marker string ("?", "<no script>", etc.) on lookup failure
    rather than raising, so callers can filter by class name.
    """
    raw = reader.get_raw_data()
    if len(raw) < 32:
        return "?"
    file_id, path_id = struct.unpack_from("<iq", raw, 16)
    if path_id == 0:
        return "<no script>"
    af = reader.assets_file
    if file_id == 0:
        target = af.objects.get(path_id)
    else:
        try:
            ext = af.externals[file_id - 1]
        except IndexError:
            return f"<extern fid={file_id} pid={path_id}>"
        ef = getattr(ext, "assets_file", None) or getattr(ext, "asset_file", None)
        if ef is None:
            env = getattr(af, "parent", None)
            ext_name = getattr(ext, "path", None) or getattr(ext, "file_name", None)
            if env is not None and ext_name is not None:
                for fname, fobj in env.files.items():
                    if fname.endswith(ext_name) or ext_name.endswith(fname):
                        ef = fobj
                        break
        if ef is None:
            return f"<extern fid={file_id} pid={path_id}>"
        target = ef.objects.get(path_id)
    if target is None:
        return f"<not found pathID={path_id}>"
    script = target.parse_as_object()
    name = getattr(script, "m_ClassName", None) or getattr(script, "m_Name", None)
    return str(name) if name else "?"


# ============================================================
# Parsed ClutterTransforms data
# ============================================================


@dataclass(frozen=True)
class ClutterInstance:
    """A single per-instance TRS from a Model.transforms list."""

    initialized: bool
    position: tuple[float, float, float]
    rotation_euler: tuple[float, float, float]  # degrees, Unity ZXY-intrinsic
    scale: tuple[float, float, float]


@dataclass(frozen=True)
class ClutterModel:
    initialized: bool
    mesh: PPtr
    material: PPtr
    mesh_transform: ClutterInstance
    atlas_index: int
    instances: tuple[ClutterInstance, ...]
    ignore_heightmap: bool
    use_procedural_damage: bool
    clutter_override: int
    lod_quality_level: int
    show: bool


@dataclass(frozen=True)
class ParsedClutterTransforms:
    fade_out_when_occupied: bool
    use_static_batching: bool
    use_indirect_instancing: bool
    use_heightmap: bool
    use_world_tiling: bool
    # TilingProperties (nested in C#).
    tiling_non_uniform_size: bool
    tiling_zone_size: float
    tiling_zone_size_2d: tuple[float, float]
    tiling_mask: PPtr
    tiling_mask_breakpoint: float
    tiling_non_uniform_mask_scale: bool
    tiling_mask_size: float
    tiling_mask_size_2d: tuple[float, float]
    tiling_mask_channel: int
    tiling_apply_mask_in_editor: bool
    tiling_preview_mask: bool
    tiling_hide_tiled_copies_in_editor: bool
    tiling_use_world_position_for_offset_in_editor: bool
    tiling_offset_in_editor: tuple[float, float]
    # End TilingProperties.
    override_material: PPtr
    clutter_type: int
    models: tuple[ClutterModel, ...]
    gizmo_radius: float
    selected_index: int


def _adapt_pptr(d: dict[str, Any]) -> PPtr:
    return PPtr(file_id=int(d["m_FileID"]), path_id=int(d["m_PathID"]))


def _adapt_clutter_instance(d: dict[str, Any]) -> ClutterInstance:
    pos, rot, scl = d["position"], d["rotation"], d["scale"]
    return ClutterInstance(
        initialized=bool(d["initialized"]),
        position=(float(pos["x"]), float(pos["y"]), float(pos["z"])),
        rotation_euler=(float(rot["x"]), float(rot["y"]), float(rot["z"])),
        scale=(float(scl["x"]), float(scl["y"]), float(scl["z"])),
    )


def parse_clutter_transforms(
    env: Any,
    obj: Any,
) -> ParsedClutterTransforms:
    """Decode a ClutterTransforms MonoBehaviour into the dataclass shape."""
    from pinacotheca.typetree import decode_monobehaviour

    d = decode_monobehaviour(env, obj, "ClutterTransforms")
    tp = d["tilingProperties"]
    tzs2d = tp["tilingZoneSize2D"]
    tms2d = tp["maskSize2D"]
    toie = tp["tilingOffsetInEditor"]

    models: list[ClutterModel] = []
    for md in d["models"]:
        models.append(
            ClutterModel(
                initialized=bool(md["initialized"]),
                mesh=_adapt_pptr(md["mesh"]),
                material=_adapt_pptr(md["material"]),
                mesh_transform=_adapt_clutter_instance(md["meshTransform"]),
                atlas_index=int(md["atlasIndex"]),
                instances=tuple(_adapt_clutter_instance(t) for t in md["transforms"]),
                ignore_heightmap=bool(md["ignoreHeightmap"]),
                use_procedural_damage=bool(md["useProceduralDamage"]),
                clutter_override=int(md["clutterOverride"]),
                lod_quality_level=int(md["lodQualityLevel"]),
                show=bool(md["show"]),
            )
        )

    return ParsedClutterTransforms(
        fade_out_when_occupied=bool(d["fadeOutWhenOccupied"]),
        use_static_batching=bool(d["useStaticBatching"]),
        use_indirect_instancing=bool(d["useIndirectInstancing"]),
        use_heightmap=bool(d["useHeightmap"]),
        use_world_tiling=bool(d["useWorldTiling"]),
        tiling_non_uniform_size=bool(tp["nonUniformSize"]),
        tiling_zone_size=float(tp["tilingZoneSize"]),
        tiling_zone_size_2d=(float(tzs2d["x"]), float(tzs2d["y"])),
        tiling_mask=_adapt_pptr(tp["mask"]),
        tiling_mask_breakpoint=float(tp["maskBreakpoint"]),
        tiling_non_uniform_mask_scale=bool(tp["nonUniformMaskScale"]),
        tiling_mask_size=float(tp["maskSize"]),
        tiling_mask_size_2d=(float(tms2d["x"]), float(tms2d["y"])),
        tiling_mask_channel=int(tp["maskChannel"]),
        tiling_apply_mask_in_editor=bool(tp["applyMaskInEditor"]),
        tiling_preview_mask=bool(tp["previewMask"]),
        tiling_hide_tiled_copies_in_editor=bool(tp["hideTiledCopiesInEditor"]),
        tiling_use_world_position_for_offset_in_editor=bool(
            tp["useWorldPositionForOffsetInEditor"]
        ),
        tiling_offset_in_editor=(float(toie["x"]), float(toie["y"])),
        override_material=_adapt_pptr(d["overrideMaterial"]),
        clutter_type=int(d["clutterType"]),
        models=tuple(models),
        gizmo_radius=float(d["gizmoRadius"]),
        selected_index=int(d["selectedIndex"]),
    )


# ============================================================
# Prefab-tree walker + PrefabPart expander
# ============================================================


def euler_to_mat3(ex_deg: float, ey_deg: float, ez_deg: float) -> NDArray[np.float64]:
    """Build a 3x3 rotation matrix from Unity euler angles.

    Unity Quaternion.Euler(x, y, z) applies rotations in ZXY intrinsic order
    (Z first, then X, then Y; per the scripting reference). Equivalently, in
    extrinsic order it's YXZ — the column-vector form is `Ry @ Rx @ Rz`.
    """
    cx, sx = float(np.cos(np.radians(ex_deg))), float(np.sin(np.radians(ex_deg)))
    cy, sy = float(np.cos(np.radians(ey_deg))), float(np.sin(np.radians(ey_deg)))
    cz, sz = float(np.cos(np.radians(ez_deg))), float(np.sin(np.radians(ez_deg)))
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]], dtype=np.float64)
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=np.float64)
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]], dtype=np.float64)
    return ry @ rx @ rz


def trs_from_instance(inst: ClutterInstance) -> NDArray[np.float64]:
    """Build the 4x4 TRS matrix for a parsed ClutterInstance."""
    m = np.eye(4, dtype=np.float64)
    r = euler_to_mat3(*inst.rotation_euler)
    sx, sy, sz = inst.scale
    m[:3, :3] = r * np.array([sx, sy, sz], dtype=np.float64)
    m[0, 3] = inst.position[0]
    m[1, 3] = inst.position[1]
    m[2, 3] = inst.position[2]
    return m


def _walk_prefab_with_world(root_go: Any) -> list[tuple[Any, NDArray[np.float64]]]:
    """Walk the Transform tree from a root GameObject and yield every
    active node as (GameObject, world_matrix) pairs.

    Mirrors `prefab.walk_prefab`'s recursion (same world-matrix accumulation,
    same m_IsActive filter) but yields every GameObject — not just MeshFilter
    leaves — so a caller can locate a MonoBehaviour at any depth.
    """
    out: list[tuple[Any, NDArray[np.float64]]] = []

    root_t = _component_by_type(root_go, "Transform")
    if root_t is None:
        return out

    def recurse(transform: Any, parent_world: NDArray[np.float64]) -> None:
        local = trs_matrix(
            getattr(transform, "m_LocalPosition", None),
            getattr(transform, "m_LocalRotation", None),
            getattr(transform, "m_LocalScale", None),
        )
        world = parent_world @ local

        go_pptr = getattr(transform, "m_GameObject", None)
        if go_pptr is None or not bool(go_pptr):
            return
        try:
            go = go_pptr.deref_parse_as_object()
        except Exception:
            return
        if getattr(go, "m_IsActive", True) is False:
            return

        out.append((go, world.copy()))

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
    return out


def find_clutter_transforms_in_prefab(
    root_go: Any,
) -> list[tuple[ParsedClutterTransforms, NDArray[np.float64]]]:
    """Descend the prefab tree, find every ClutterTransforms MonoBehaviour,
    and pair each parsed instance with the world matrix of its hosting GO.

    Find by script class, not GameObject name — names vary across capitals
    (`GeeceCapitalTrans`, `rome-Capital`, Egypt's nested same-name child).
    Parse failures raise; raw-data failures log + skip.
    """
    found: list[tuple[ParsedClutterTransforms, NDArray[np.float64]]] = []
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
            if cls != "ClutterTransforms":
                continue
            try:
                parsed = parse_clutter_transforms(r.assets_file.parent, r)
            except Exception as e:
                logger.warning("ClutterTransforms decode failed: %s", e)
                continue
            found.append((parsed, world))
    return found


def _resolve_pptr_to_reader(env: Any, pptr: PPtr) -> Any | None:
    """Resolve a hand-parsed PPtr to its UnityPy ObjectReader.

    file_id==0 (intra-file refs, the common case for clutter meshes /
    materials living next to the prefab) is scoped to resources.assets.
    Cross-file refs fall back to a broader scan of loaded files.
    """
    if pptr.is_null():
        return None
    if pptr.file_id == 0:
        return find_object_by_path_id(env, pptr.path_id)
    for fname, f in env.files.items():
        if fname.endswith(".resS"):
            continue
        target = getattr(f, "objects", {}).get(pptr.path_id)
        if target is not None:
            return target
    return None


def clutter_to_prefab_parts(
    env: Any,
    parsed: ParsedClutterTransforms,
    parent_world: NDArray[np.float64],
) -> list[PrefabPart]:
    """Expand a parsed ClutterTransforms into one PrefabPart per (model, instance).

    World matrix per instance: `parent_world @ instance.TRS`. This matches
    the runtime path in `ClutterTransforms.DrawMeshes` (line 349):
    `transform.localToWorldMatrix * matrix4x_tiling * transform.Matrix`,
    where matrix4x_tiling is identity for non-tiling targets. `meshTransform`
    is data-only and not consumed by the runtime.

    Material selection mirrors `Regenerate` (line 275): overrideMaterial wins
    when set, otherwise the per-model material.
    """
    typed = clutter_to_prefab_parts_with_type(env, parsed, parent_world)
    return [part for part, _ in typed]


# TerrainClutterType enum (decompiled/Assembly-CSharp/TerrainClutterType.cs):
#   None = -1, Trees = 0, MinorBuildings = 1, MajorBuildings = 2
TERRAIN_CLUTTER_TYPE_NONE = -1


def clutter_to_prefab_parts_with_type(
    env: Any,
    parsed: ParsedClutterTransforms,
    parent_world: NDArray[np.float64],
) -> list[tuple[PrefabPart, int]]:
    """Same expansion as `clutter_to_prefab_parts`, but each part is paired
    with its resolved `TerrainClutterType` (int). Resolution rule mirrors
    `ClutterTransformsBackgroundData.AddModel:90-93`:

        if model.clutter_override != TerrainClutterType.None:
            type = model.clutter_override
        else:
            type = parent.clutter_type

    The cull pass in `clutter_culling.py` reads the per-instance type to
    decide which mask channel to sample.
    """
    if parsed.use_world_tiling:
        raise NotImplementedError(
            "ClutterTransforms.useWorldTiling=True is not yet supported. "
            "If a target uses tiling, decide whether to honor or skip per instance."
        )

    out: list[tuple[PrefabPart, int]] = []
    for model in parsed.models:
        if not model.show:
            continue
        mesh_reader = _resolve_pptr_to_reader(env, model.mesh)
        if mesh_reader is None:
            logger.debug("Clutter mesh PPtr did not resolve: %s", model.mesh)
            continue
        if mesh_reader.type.name != "Mesh":
            logger.debug("Clutter mesh PPtr resolved to %s, not Mesh", mesh_reader.type.name)
            continue

        if not parsed.override_material.is_null():
            material_pptr = parsed.override_material
        else:
            material_pptr = model.material
        materials: list[Any] = []
        mat_reader = _resolve_pptr_to_reader(env, material_pptr)
        if mat_reader is not None and mat_reader.type.name == "Material":
            materials.append(ObjectReaderAsPPtr(mat_reader))

        if model.clutter_override != TERRAIN_CLUTTER_TYPE_NONE:
            resolved_type = model.clutter_override
        else:
            resolved_type = parsed.clutter_type

        mesh_obj = ObjectReaderAsPPtr(mesh_reader)
        for inst in model.instances:
            world = parent_world @ trs_from_instance(inst)
            part = PrefabPart(
                mesh_obj=mesh_obj,
                world_matrix=world,
                materials=materials,
            )
            out.append((part, resolved_type))
    return out
