"""Synthetic tests for the prefab transform-baking pipeline.

These tests use plain numpy + duck-typed structs (no real UnityPy or
game data). They cover the core math: TRS composition, normal transform
under non-uniform scale, mirrored-scale winding flip, and the single
X-negation that converts Unity left-handed coords to OBJ right-handed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from pinacotheca.prefab import (
    PrefabPart,
    bake_to_obj,
    drop_splat_meshes,
    find_geometry_y_min,
    find_ground_y,
    quat_to_mat3,
    strip_plinth_from_obj,
    trs_matrix,
)


@dataclass
class V3:
    x: float
    y: float
    z: float


@dataclass
class Q:
    x: float
    y: float
    z: float
    w: float


# --- Quaternion / matrix math ----------------------------------------------


def test_quat_identity() -> None:
    m = quat_to_mat3(Q(0, 0, 0, 1))
    assert np.allclose(m, np.eye(3))


def test_quat_y_90() -> None:
    # 90° rotation around Y: (0, sin45, 0, cos45)
    s = (2**0.5) / 2
    m = quat_to_mat3(Q(0, s, 0, s))
    # Rotates (1, 0, 0) to (0, 0, -1) under standard right-handed convention
    v = np.array([1.0, 0.0, 0.0])
    rotated = m @ v
    assert np.allclose(rotated, [0.0, 0.0, -1.0], atol=1e-6)


def test_trs_identity() -> None:
    m = trs_matrix(V3(0, 0, 0), Q(0, 0, 0, 1), V3(1, 1, 1))
    assert np.allclose(m, np.eye(4))


def test_trs_translation_then_scale() -> None:
    # A vertex at (1, 0, 0) in local space, with scale=(2,2,2) and
    # translation=(10, 0, 0) should land at (12, 0, 0): scale first (2,0,0)
    # then translate (12, 0, 0).
    m = trs_matrix(V3(10, 0, 0), Q(0, 0, 0, 1), V3(2, 2, 2))
    v = np.array([1.0, 0.0, 0.0, 1.0])
    out = m @ v
    assert np.allclose(out[:3], [12.0, 0.0, 0.0])


def test_trs_chain_translation() -> None:
    # parent translates +5x; child translates +3x in parent's frame.
    # A vertex at origin under the child should be at 8x in world.
    parent = trs_matrix(V3(5, 0, 0), Q(0, 0, 0, 1), V3(1, 1, 1))
    child = trs_matrix(V3(3, 0, 0), Q(0, 0, 0, 1), V3(1, 1, 1))
    world = parent @ child
    out = world @ np.array([0.0, 0.0, 0.0, 1.0])
    assert np.allclose(out[:3], [8.0, 0.0, 0.0])


def test_normal_transform_under_nonuniform_scale() -> None:
    """Normal must use inverse-transpose under non-uniform scale."""
    from pinacotheca.prefab import _normal_matrix

    m = trs_matrix(V3(0, 0, 0), Q(0, 0, 0, 1), V3(2, 1, 1))[:3, :3]
    nm = _normal_matrix(m)
    # Direct apply: m @ (1, 1, 0) = (2, 1, 0); a "normal-transformed"
    # version using inverse-transpose stretches the OTHER axis.
    n = np.array([1.0, 1.0, 0.0]) / np.sqrt(2)
    transformed = nm @ n
    transformed = transformed / np.linalg.norm(transformed)
    # Inverse-transpose of diag(2,1,1) is diag(0.5, 1, 1).
    # diag(0.5, 1, 1) @ (1, 1, 0)/sqrt(2) = (0.5, 1, 0)/sqrt(2) -> normalized
    expected = np.array([0.5, 1.0, 0.0])
    expected = expected / np.linalg.norm(expected)
    assert np.allclose(transformed, expected, atol=1e-6)


# --- bake_to_obj ------------------------------------------------------------


@dataclass
class _FakeMesh:
    """Mimics enough of UnityPy's Mesh + MeshHandler interface for the
    bake_to_obj test path."""

    m_Name: str
    m_VertexCount: int
    m_Vertices: list[tuple[float, float, float]]
    m_UV0: list[tuple[float, float]]
    m_Normals: list[tuple[float, float, float]]
    m_SubMeshes: list[Any]
    triangles: list[list[tuple[int, int, int]]]


class _MeshObj:
    """Wrapper that mimics a UnityPy mesh PPtr.deref_parse_as_object() result."""

    def __init__(self, mesh: _FakeMesh) -> None:
        self._mesh = mesh

    def deref_parse_as_object(self) -> _FakeMesh:
        return self._mesh


def _patch_mesh_handler(monkeypatch: Any) -> None:
    """Monkeypatch UnityPy's MeshHandler so bake_to_obj uses our fake meshes."""

    class _FakeHandler:
        def __init__(self, mesh: _FakeMesh) -> None:
            self._m = mesh

        def process(self) -> None:
            return None

        @property
        def m_VertexCount(self) -> int:
            return self._m.m_VertexCount

        @property
        def m_Vertices(self) -> list[tuple[float, float, float]]:
            return self._m.m_Vertices

        @property
        def m_UV0(self) -> list[tuple[float, float]]:
            return self._m.m_UV0

        @property
        def m_Normals(self) -> list[tuple[float, float, float]]:
            return self._m.m_Normals

        def get_triangles(self) -> list[list[tuple[int, int, int]]]:
            return self._m.triangles

    import sys

    fake_module = type(sys)("UnityPy.helpers.MeshHelper")
    fake_module.MeshHandler = _FakeHandler  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "UnityPy.helpers.MeshHelper", fake_module)


def test_bake_to_obj_x_flip_once(monkeypatch: Any) -> None:
    """A single triangle with one vertex at Unity-space (+1, 0, 0) should
    appear at OBJ-space (-1, 0, 0). Verifies the X-flip happens exactly
    once during bake_to_obj."""
    mesh = _FakeMesh(
        m_Name="cube",
        m_VertexCount=3,
        m_Vertices=[(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)],
        m_UV0=[(0.0, 0.0), (1.0, 0.0), (0.5, 1.0)],
        m_Normals=[(0.0, 0.0, 1.0)] * 3,
        m_SubMeshes=[],
        triangles=[[(0, 1, 2)]],
    )
    _patch_mesh_handler(monkeypatch)
    parts = [
        PrefabPart(
            mesh_obj=_MeshObj(mesh),
            world_matrix=np.eye(4),
            materials=[],
        )
    ]
    obj = bake_to_obj(parts)
    # First vertex line should be 'v -1 0 0' (the +X = 1 input flipped to -1)
    v_lines = [ln for ln in obj.splitlines() if ln.startswith("v ")]
    assert len(v_lines) == 3
    parts0 = v_lines[0].split()
    assert float(parts0[1]) == -1.0
    assert float(parts0[2]) == 0.0
    assert float(parts0[3]) == 0.0


def test_bake_to_obj_translation_chain(monkeypatch: Any) -> None:
    """Vertex at local (0, 0, 0) under a world matrix that translates
    +5x should end up at OBJ-space (-5, 0, 0)."""
    mesh = _FakeMesh(
        m_Name="dot",
        m_VertexCount=1,
        m_Vertices=[(0.0, 0.0, 0.0)],
        m_UV0=[],
        m_Normals=[],
        m_SubMeshes=[],
        triangles=[],
    )
    _patch_mesh_handler(monkeypatch)
    world = trs_matrix(V3(5, 0, 0), Q(0, 0, 0, 1), V3(1, 1, 1))
    parts = [PrefabPart(mesh_obj=_MeshObj(mesh), world_matrix=world, materials=[])]
    obj = bake_to_obj(parts)
    v_line = next(ln for ln in obj.splitlines() if ln.startswith("v "))
    coords = [float(x) for x in v_line.split()[1:]]
    assert coords == [-5.0, 0.0, 0.0]


def test_bake_to_obj_negative_scale_flips_winding(monkeypatch: Any) -> None:
    """Mirrored part (negative scale → det<0): triangle indices emit in
    original (a, b, c) order rather than the reversed (c, b, a) used for
    standard parts. This cancels the X-flip's secondary winding effect."""
    mesh = _FakeMesh(
        m_Name="tri",
        m_VertexCount=3,
        m_Vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        m_UV0=[],
        m_Normals=[],
        m_SubMeshes=[],
        triangles=[[(0, 1, 2)]],
    )
    _patch_mesh_handler(monkeypatch)
    # det < 0 because one axis is negated
    world = trs_matrix(V3(0, 0, 0), Q(0, 0, 0, 1), V3(-1, 1, 1))
    parts = [PrefabPart(mesh_obj=_MeshObj(mesh), world_matrix=world, materials=[])]
    obj = bake_to_obj(parts)
    f_line = next(ln for ln in obj.splitlines() if ln.startswith("f "))
    # Indices are 1-based. With flip_winding=True we emit (1, 2, 3) not (3, 2, 1).
    parts0 = [token.split("/")[0] for token in f_line.split()[1:]]
    assert parts0 == ["1", "2", "3"]


# --- drop_splat_meshes ------------------------------------------------------


@dataclass
class _FakeMaterial:
    m_Name: str


class _MaterialPPtr:
    """Mimics a UnityPy material PPtr — `bool()` and `deref_parse_as_object()`."""

    def __init__(self, name: str) -> None:
        self._mat = _FakeMaterial(m_Name=name)

    def __bool__(self) -> bool:
        return True

    def deref_parse_as_object(self) -> _FakeMaterial:
        return self._mat


def _part_with_material(name: str) -> PrefabPart:
    return PrefabPart(
        mesh_obj=None,
        world_matrix=np.eye(4),
        materials=[_MaterialPPtr(name)],
    )


def test_drop_splat_meshes_drops_splat_prefix() -> None:
    parts = [
        _part_with_material("SplatHeightDefault"),
        _part_with_material("SplatTextureDefaultPVT"),
        _part_with_material("SplatClutterDefault"),
        _part_with_material("Library"),
    ]
    kept = drop_splat_meshes(parts)
    assert len(kept) == 1
    assert kept[0].materials[0].deref_parse_as_object().m_Name == "Library"


def test_drop_splat_meshes_drops_water_no_foam() -> None:
    parts = [
        _part_with_material("WaterNoFoam"),
        _part_with_material("Watermill_DIFF"),
    ]
    kept = drop_splat_meshes(parts)
    assert len(kept) == 1
    assert kept[0].materials[0].deref_parse_as_object().m_Name == "Watermill_DIFF"


def test_drop_splat_meshes_keeps_normal_materials() -> None:
    parts = [
        _part_with_material("Watermill_DIFF"),
        _part_with_material("Library"),
        _part_with_material("Maurya_Capital"),
        _part_with_material("Granary"),
    ]
    kept = drop_splat_meshes(parts)
    assert len(kept) == 4


def test_drop_splat_meshes_returns_original_if_all_dropped() -> None:
    """Defensive fallback: if filter would empty a non-empty input, return
    the original list unchanged."""
    parts = [
        _part_with_material("SplatHeightDefault"),
        _part_with_material("WaterNoFoam"),
    ]
    kept = drop_splat_meshes(parts)
    assert kept == parts


# --- strip_plinth_from_obj --------------------------------------------------


def _obj_from_verts_and_faces(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
) -> str:
    """Build a minimal OBJ string from vertex positions and 1-based faces."""
    lines: list[str] = []
    for vx, vy, vz in vertices:
        lines.append(f"v {vx} {vy} {vz}")
    for a, b, c in faces:
        lines.append(f"f {a} {b} {c}")
    return "\n".join(lines)


def test_strip_plinth_no_plinth_unchanged() -> None:
    """A Granary-shaped mesh — small footprint at the bottom, full
    structure above — should not trigger plinth detection."""
    # Bottom slice (y=0) covers a tiny 1x1 footprint; top slice (y=10)
    # covers a much larger 10x10 footprint. Bottom area / full area = 1%.
    vertices = [
        # Bottom (small)
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0),
        # Top (large)
        (-5.0, 10.0, -5.0),
        (5.0, 10.0, -5.0),
        (5.0, 10.0, 5.0),
        (-5.0, 10.0, 5.0),
    ]
    faces = [(1, 2, 3), (4, 5, 6), (4, 6, 7)]
    obj = _obj_from_verts_and_faces(vertices, faces)
    out = strip_plinth_from_obj(obj)
    assert out == obj


def test_strip_plinth_drops_bottom_triangles() -> None:
    """A Library-shaped mesh — full-footprint slab at the bottom plus a
    small structure above — should detect the plinth and drop the slab
    triangles."""
    # Slab covers the full 10x10 XZ footprint at y=0.
    # Upper structure is a small tetrahedron at y=5..10 within the same
    # XZ extent. Bottom 5% Y = anything with y <= 0.5.
    vertices = [
        # Slab corners (y=0)
        (-5.0, 0.0, -5.0),
        (5.0, 0.0, -5.0),
        (5.0, 0.0, 5.0),
        (-5.0, 0.0, 5.0),
        # Upper tetra
        (-1.0, 5.0, -1.0),
        (1.0, 5.0, -1.0),
        (0.0, 10.0, 0.0),
        (0.0, 5.0, 1.0),
    ]
    # 2 slab tris + 4 upper tris (tetra has 4 faces)
    faces = [
        (1, 2, 3),  # slab tri 1 — should drop
        (1, 3, 4),  # slab tri 2 — should drop
        (5, 6, 7),  # upper — keep
        (5, 7, 8),  # upper — keep
        (6, 8, 7),  # upper — keep
        (5, 8, 6),  # upper — keep (last face touches y=5 which is above cut)
    ]
    obj = _obj_from_verts_and_faces(vertices, faces)
    out = strip_plinth_from_obj(obj)
    f_lines = [ln for ln in out.splitlines() if ln.startswith("f ")]
    # All 4 upper triangles preserved, both slab triangles dropped.
    assert len(f_lines) == 4


def test_strip_plinth_dynamic_cut_catches_thick_slab() -> None:
    """Library-shaped mesh: a slab spanning 30% of vertical extent (not just
    the bottom 5%) should still be removed entirely — including the slab's
    top face and side walls, not just its bottom face. This exercises the
    density-based cut height; a static 5% cut would only drop the very
    bottom and leave the slab walls + top behind (the Library bug)."""
    # y_min=0, y_max=10, extent=10. Slab spans y=0..3 (30% of extent),
    # building proper at y=5..10 with high density to mark where the
    # building begins.
    vertices: list[tuple[float, float, float]] = []
    # Slab corners — bottom (y=0) and top (y=3) of slab
    for y in (0.0, 3.0):
        vertices.extend([(-5.0, y, -5.0), (5.0, y, -5.0), (5.0, y, 5.0), (-5.0, y, 5.0)])
    # Building proper — dense vertex cluster from y=5 up to y=10. Multiple
    # Y values so the density bin lands exactly at y=5 (not above the cap).
    for _ in range(20):
        for y in (5.0, 6.0, 7.0, 8.0, 9.0, 10.0):
            vertices.append((0.0, y, 0.0))
    # Vertex indices (1-based): slab bottom 1..4, slab top 5..8, building 9+.
    # Building tri uses verts strictly above cut so it survives.
    faces = [
        (1, 2, 3),  # slab bottom — drop
        (1, 3, 4),  # slab bottom — drop
        (5, 6, 7),  # slab top — drop (y=3, all ≤ cut_y=5)
        (5, 7, 8),  # slab top — drop
        (1, 2, 5),  # slab side — drop (y=0,0,3 all ≤ 5)
        (15, 16, 17),  # building tri — keep (verts at y>=6)
    ]
    obj = _obj_from_verts_and_faces(vertices, faces)
    out = strip_plinth_from_obj(obj)
    f_lines = [ln for ln in out.splitlines() if ln.startswith("f ")]
    # Only the building tri should survive.
    assert len(f_lines) == 1
    assert f_lines[0].split()[1:] == ["15", "16", "17"]


def test_strip_plinth_clamps_straddling_slab_walls() -> None:
    """Library-shaped slab where the side walls are SINGLE long triangles
    spanning from y=0 (slab bottom) to y=6 (into the building above the
    cut). Triangle-drop alone leaves these walls because they straddle
    the cut. Vertex clamping pulls the bottom verts up to cut_y, flattening
    the slab walls to a thin disc."""
    vertices: list[tuple[float, float, float]] = []
    # Slab bottom corners (y=0) — full footprint 10x10
    vertices.extend([(-5.0, 0.0, -5.0), (5.0, 0.0, -5.0), (5.0, 0.0, 5.0), (-5.0, 0.0, 5.0)])
    # Building wall verts at y=6 (above cut)
    vertices.extend([(-5.0, 6.0, -5.0), (5.0, 6.0, -5.0), (5.0, 6.0, 5.0), (-5.0, 6.0, 5.0)])
    # Building density to set cut_y near building start
    for _ in range(20):
        for y in (5.0, 6.0, 7.0, 8.0, 9.0, 10.0):
            vertices.append((0.0, y, 0.0))
    # Side wall: long tri spanning bottom (y=0) → top (y=6). Without clamping
    # this survives because verts 1, 2, 5 are not all ≤ cut_y=5.
    faces = [(1, 2, 5)]
    obj = _obj_from_verts_and_faces(vertices, faces)
    out = strip_plinth_from_obj(obj)
    # Tri survives, but its y=0 verts (idx 1, 2) are clamped to cut_y=5.
    f_lines = [ln for ln in out.splitlines() if ln.startswith("f ")]
    assert len(f_lines) == 1
    # Check vert 1 (originally y=0) is clamped to cut_y=5
    v_lines = [ln for ln in out.splitlines() if ln.startswith("v ")]
    v1 = [float(x) for x in v_lines[0].split()[1:]]
    assert v1[1] == 5.0  # was y=0, clamped
    v5 = [float(x) for x in v_lines[4].split()[1:]]
    assert v5[1] == 6.0  # above cut, unchanged


def test_strip_plinth_threshold_default_80() -> None:
    """At the default 0.80 threshold, a bottom footprint that's exactly
    80% of the full footprint should trigger (since the comparison is
    strict less-than)."""
    # Full footprint: 10x10 = 100. Bottom 5% slice covers 8x10 = 80.
    # ratio = 0.80, strictly NOT less than threshold → triggers strip.
    vertices = [
        # Bottom slab covering 8x10 of the 10x10 full footprint
        (-4.0, 0.0, -5.0),
        (4.0, 0.0, -5.0),
        (4.0, 0.0, 5.0),
        (-4.0, 0.0, 5.0),
        # Upper structure spans the full 10x10 footprint
        (-5.0, 10.0, -5.0),
        (5.0, 10.0, -5.0),
        (5.0, 10.0, 5.0),
        (-5.0, 10.0, 5.0),
    ]
    faces = [
        (1, 2, 3),  # slab — should drop
        (1, 3, 4),  # slab — should drop
        (5, 6, 7),  # upper — keep
        (5, 7, 8),  # upper — keep
    ]
    obj = _obj_from_verts_and_faces(vertices, faces)
    out = strip_plinth_from_obj(obj)
    f_lines = [ln for ln in out.splitlines() if ln.startswith("f ")]
    assert len(f_lines) == 2


# --- strip_plinth_from_obj cut_y_override -----------------------------------


def test_strip_plinth_override_applied_at_exact_y() -> None:
    """When cut_y_override is provided and passes safety guards, cut occurs
    at exactly that Y regardless of vertex density. Also verifies the override
    bypasses the footprint detection — even a non-plinth-shaped mesh gets
    clamped if the override passes."""
    # 1 vert at y=0 (below cut), 4 verts at y=1 (above) — only 20% will be
    # clamped, well under the 50%-vert-count guard. Cut at 0.5 is also under
    # the 65%-of-extent guard (max_cut_y = 0 + 0.65*1 = 0.65).
    vertices = [
        (0.0, 0.0, 0.0),  # below cut — should be clamped
        (1.0, 1.0, 0.0),
        (0.0, 1.0, 1.0),
        (1.0, 1.0, 1.0),
        (0.5, 1.0, 0.5),
    ]
    faces = [(1, 2, 3), (2, 3, 4), (3, 4, 5)]
    obj = _obj_from_verts_and_faces(vertices, faces)
    out = strip_plinth_from_obj(obj, cut_y_override=0.5)
    v_lines = [ln for ln in out.splitlines() if ln.startswith("v ")]
    # Vert 1 (y=0) clamped to 0.5; verts 2-5 (y=1) unchanged.
    assert float(v_lines[0].split()[2]) == 0.5
    assert float(v_lines[1].split()[2]) == 1.0
    assert float(v_lines[2].split()[2]) == 1.0
    assert float(v_lines[3].split()[2]) == 1.0
    assert float(v_lines[4].split()[2]) == 1.0


def test_strip_plinth_override_rejected_by_extent_guard() -> None:
    """An override that would cut more than max_cut_fraction (default 0.65)
    of the model's Y extent is refused; falls through to density heuristic.
    Here the heuristic returns the OBJ unchanged because no plinth shape
    is detected."""
    # Extent y=0..1. cut_y_override=0.9 would cut 90% (>65% cap). Refused.
    vertices = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.5, 1.0, 0.5),
    ]
    faces = [(1, 2, 3)]
    obj = _obj_from_verts_and_faces(vertices, faces)
    out = strip_plinth_from_obj(obj, cut_y_override=0.9)
    # Heuristic doesn't fire (no plinth shape) → unchanged.
    assert out == obj


def test_strip_plinth_override_rejected_by_vert_count_guard() -> None:
    """An override that would clamp ≥50% of vertices is refused. With 5
    verts at y=0 and 5 verts at y=10, an override at y=5 would clamp the
    bottom 5 (50%) — guard triggers."""
    vertices: list[tuple[float, float, float]] = []
    # 5 verts at y=0 (would all be clamped if override accepted)
    for i in range(5):
        vertices.append((float(i), 0.0, 0.0))
    # 5 verts at y=10
    for i in range(5):
        vertices.append((float(i), 10.0, 0.0))
    faces = [(1, 2, 6), (3, 4, 7)]
    obj = _obj_from_verts_and_faces(vertices, faces)
    # Override at y=5 lies within the 65%-of-extent cap (cap is at y=6.5)
    # so the extent guard passes; but it would clamp 5 of 10 verts (50%),
    # which is ≥50%, so the vert-count guard refuses it.
    out = strip_plinth_from_obj(obj, cut_y_override=5.0)
    # Guard refused → no plinth detected by heuristic either → unchanged.
    assert out == obj


def test_strip_plinth_override_none_preserves_existing_behavior() -> None:
    """Regression: cut_y_override=None (default) should produce identical
    output to omitting the parameter entirely. Reuses the canonical Library
    test scenario."""
    vertices = [
        (-5.0, 0.0, -5.0),
        (5.0, 0.0, -5.0),
        (5.0, 0.0, 5.0),
        (-5.0, 0.0, 5.0),
        (-1.0, 5.0, -1.0),
        (1.0, 5.0, -1.0),
        (0.0, 10.0, 0.0),
        (0.0, 5.0, 1.0),
    ]
    faces = [(1, 2, 3), (1, 3, 4), (5, 6, 7), (5, 7, 8), (6, 8, 7), (5, 8, 6)]
    obj = _obj_from_verts_and_faces(vertices, faces)
    a = strip_plinth_from_obj(obj)
    b = strip_plinth_from_obj(obj, cut_y_override=None)
    assert a == b


# --- find_ground_y / find_geometry_y_min ------------------------------------


def _ground_part(material_name: str, world_y: float) -> PrefabPart:
    """Build a synthetic part: one vertex at (0, world_y, 0) with the given
    material. Identity world matrix so the input Y is also the world Y."""
    mesh = _FakeMesh(
        m_Name=f"plane_{material_name}",
        m_VertexCount=1,
        m_Vertices=[(0.0, world_y, 0.0)],
        m_UV0=[],
        m_Normals=[],
        m_SubMeshes=[],
        triangles=[],
    )
    return PrefabPart(
        mesh_obj=_MeshObj(mesh),
        world_matrix=np.eye(4),
        materials=[_MaterialPPtr(material_name)],
    )


def test_find_ground_y_prefers_height_default(monkeypatch: Any) -> None:
    """SplatHeightDefault wins over SplatClutterDefault when both present."""
    _patch_mesh_handler(monkeypatch)
    parts = [
        _ground_part("SplatHeightDefault", 0.30),
        _ground_part("SplatClutterDefault", 0.99),  # should be ignored
        _ground_part("Library", 5.0),  # building geometry; ignored
    ]
    assert find_ground_y(parts) == 0.30


def test_find_ground_y_falls_back_to_clutter(monkeypatch: Any) -> None:
    """When no SplatHeightDefault, fall back to SplatClutterDefault /
    SplatTextureDefaultPVT (max across them)."""
    _patch_mesh_handler(monkeypatch)
    parts = [
        _ground_part("SplatClutterDefault", 0.10),
        _ground_part("SplatTextureDefaultPVT", 0.42),
        _ground_part("Library", 5.0),
    ]
    assert find_ground_y(parts) == 0.42


def test_find_ground_y_excludes_water(monkeypatch: Any) -> None:
    """Water-surface materials sit ABOVE ground (visible bath/pond water)
    and must not contaminate the ground-line measurement."""
    _patch_mesh_handler(monkeypatch)
    parts = [
        _ground_part("SplatHeightDefault", 0.0),
        _ground_part("BathWater", 1.5),
        _ground_part("WaterNoFoam", 2.0),
    ]
    assert find_ground_y(parts) == 0.0


def test_find_ground_y_returns_none_when_no_splats(monkeypatch: Any) -> None:
    """Most religious buildings ship without splat planes; helper returns
    None and the caller falls back to the density heuristic."""
    _patch_mesh_handler(monkeypatch)
    parts = [
        _ground_part("Library", 5.0),
        _ground_part("Granary", 3.0),
    ]
    assert find_ground_y(parts) is None


def test_find_ground_y_returns_none_when_only_water(monkeypatch: Any) -> None:
    _patch_mesh_handler(monkeypatch)
    parts = [_ground_part("BathWater", 1.0)]
    assert find_ground_y(parts) is None


def test_find_geometry_y_min_excludes_splats(monkeypatch: Any) -> None:
    """Used by the composite-prefab defensive check: returns the min Y
    across non-splat parts so we can compare splat-Y to it."""
    _patch_mesh_handler(monkeypatch)
    parts = [
        _ground_part("SplatHeightDefault", -0.5),  # ignored — splat
        _ground_part("Library", -2.0),  # building geometry; counted
        _ground_part("Granary", 1.0),
    ]
    assert find_geometry_y_min(parts) == -2.0


# --- bake_to_obj pre_rotation_y_deg -----------------------------------------


def test_bake_to_obj_pre_rotation_180_flips_z(monkeypatch: Any) -> None:
    """A vertex at Unity-space (0, 0, 1) — the building's "front" by
    convention — should appear at OBJ-space (0, 0, -1) after the 180°
    Y-rotation pre-multiplied into the world matrix. The X-flip in the
    bake then preserves left/right correctly. Same applies to normals."""
    mesh = _FakeMesh(
        m_Name="dot",
        m_VertexCount=1,
        m_Vertices=[(0.0, 0.0, 1.0)],
        m_UV0=[],
        m_Normals=[(0.0, 0.0, 1.0)],
        m_SubMeshes=[],
        triangles=[],
    )
    _patch_mesh_handler(monkeypatch)
    parts = [PrefabPart(mesh_obj=_MeshObj(mesh), world_matrix=np.eye(4), materials=[])]

    obj = bake_to_obj(parts, pre_rotation_y_deg=180.0)
    v_line = next(ln for ln in obj.splitlines() if ln.startswith("v "))
    coords = [float(x) for x in v_line.split()[1:]]
    np.testing.assert_allclose(coords, [0.0, 0.0, -1.0], atol=1e-6)

    n_line = next(ln for ln in obj.splitlines() if ln.startswith("vn "))
    n_coords = [float(x) for x in n_line.split()[1:]]
    np.testing.assert_allclose(n_coords, [0.0, 0.0, -1.0], atol=1e-6)


def test_bake_to_obj_pre_rotation_default_unchanged(monkeypatch: Any) -> None:
    """Regression: omitting pre_rotation_y_deg or passing 0.0 produces
    identical output to the historical (no-rotation) behavior."""
    mesh = _FakeMesh(
        m_Name="dot",
        m_VertexCount=1,
        m_Vertices=[(0.0, 0.0, 1.0)],
        m_UV0=[],
        m_Normals=[(0.0, 0.0, 1.0)],
        m_SubMeshes=[],
        triangles=[],
    )
    _patch_mesh_handler(monkeypatch)
    parts = [PrefabPart(mesh_obj=_MeshObj(mesh), world_matrix=np.eye(4), materials=[])]
    a = bake_to_obj(parts)
    b = bake_to_obj(parts, pre_rotation_y_deg=0.0)
    assert a == b
    # And the single vertex is at the original (X-flipped) location.
    v_line = next(ln for ln in a.splitlines() if ln.startswith("v "))
    coords = [float(x) for x in v_line.split()[1:]]
    np.testing.assert_allclose(coords, [0.0, 0.0, 1.0], atol=1e-6)
