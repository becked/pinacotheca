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
    quat_to_mat3,
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
