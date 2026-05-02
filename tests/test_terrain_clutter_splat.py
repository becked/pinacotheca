"""Unit tests for the TerrainClutterSplat per-channel mask compositor.

The MonoBehaviour decoder is exercised by `test_typetree.py` against the
real game env; these tests cover the in-process compose pass in
`compose_clutter_mask_texture` (pixel-channel routing, intensity scaling,
clamping, null-PPtr handling).
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from pinacotheca.terrain_clutter_splat import (
    ClutterMaskPart,
    TerrainClutterSplatFields,
    compose_clutter_mask_texture,
)


def _make_part(
    *,
    cluttermask_pid: int = 1,
    channel: int = 2,
    intensity: float = 1.0,
    clear_trees: bool = False,
    clear_minor: bool = True,
    clear_major: bool = False,
) -> ClutterMaskPart:
    """Build a ClutterMaskPart with parsed-only fields filled in."""
    from pinacotheca.clutter_transforms import PPtr

    parsed = TerrainClutterSplatFields(
        sorting_offset=0,
        use_simple_mode=True,
        material=PPtr(file_id=0, path_id=0),
        cluttermask=PPtr(file_id=0, path_id=cluttermask_pid),
        override_alphamap_use_world_uvs_on=False,
        clutter_mask_channel=channel,
        alphamask=PPtr(file_id=0, path_id=0),
        clear_trees=clear_trees,
        clear_minor_buildings=clear_minor,
        clear_major_buildings=clear_major,
        clutter_intensity=intensity,
        tiling=1.0,
    )
    return ClutterMaskPart(
        parsed=parsed,
        mesh_obj=None,
        world_matrix=np.eye(4, dtype=np.float64),
        materials=[],
        host_go_name="test",
    )


class _StubReader:
    """Minimal stand-in for the resolved Texture reader; produces a fixed image
    when `parse_as_object` is called, then we monkeypatch `_decode_texture`
    to bypass UnityPy decoding."""

    def __init__(self, payload: object) -> None:
        self._payload = payload

    def parse_as_object(self) -> object:
        return self._payload


def test_compose_writes_only_flagged_channels(monkeypatch: pytest.MonkeyPatch) -> None:
    """A B-channel value of 200 with intensity 1.0, clear_minor only, should
    produce R=0, G=200, B=0 across the output image (G is MinorBuildings)."""
    from pinacotheca import terrain_clutter_splat as mod

    src_arr = np.zeros((4, 4, 4), dtype=np.uint8)
    src_arr[..., 2] = 200  # B channel
    src_img = Image.fromarray(src_arr, mode="RGBA")

    monkeypatch.setattr(mod, "_resolve_pptr_to_reader", lambda _env, _p: _StubReader(src_img))
    monkeypatch.setattr(mod, "_decode_texture", lambda obj: obj)

    part = _make_part(
        channel=2,
        intensity=1.0,
        clear_trees=False,
        clear_minor=True,
        clear_major=False,
    )
    out = compose_clutter_mask_texture(env=None, plane=part)
    assert out is not None
    arr = np.asarray(out)
    assert arr.shape == (4, 4, 3)
    assert (arr[..., 0] == 0).all(), "Trees channel should be 0 (clear_trees=False)"
    assert (arr[..., 1] == 200).all(), "MinorBuildings channel should = mask_value"
    assert (arr[..., 2] == 0).all(), "MajorBuildings channel should be 0 (clear_major=False)"


def test_compose_intensity_scales_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """clutter_intensity multiplies the mask before the per-flag write."""
    from pinacotheca import terrain_clutter_splat as mod

    src_arr = np.zeros((2, 2, 4), dtype=np.uint8)
    src_arr[..., 0] = 100  # R channel
    src_img = Image.fromarray(src_arr, mode="RGBA")
    monkeypatch.setattr(mod, "_resolve_pptr_to_reader", lambda _env, _p: _StubReader(src_img))
    monkeypatch.setattr(mod, "_decode_texture", lambda obj: obj)

    part = _make_part(
        channel=0,
        intensity=0.5,
        clear_trees=True,
        clear_minor=False,
        clear_major=False,
    )
    out = compose_clutter_mask_texture(env=None, plane=part)
    assert out is not None
    arr = np.asarray(out)
    assert (arr[..., 0] == 50).all(), "Trees channel should be mask_value * intensity"


def test_compose_clamps_when_intensity_pushes_past_255(monkeypatch: pytest.MonkeyPatch) -> None:
    """Intensity > 1.0 must clamp at 255 — the cull pass treats values
    monotonically and never wants overflow wrap-around."""
    from pinacotheca import terrain_clutter_splat as mod

    src_arr = np.zeros((2, 2, 4), dtype=np.uint8)
    src_arr[..., 0] = 200
    src_img = Image.fromarray(src_arr, mode="RGBA")
    monkeypatch.setattr(mod, "_resolve_pptr_to_reader", lambda _env, _p: _StubReader(src_img))
    monkeypatch.setattr(mod, "_decode_texture", lambda obj: obj)

    part = _make_part(
        channel=0,
        intensity=2.0,
        clear_trees=True,
        clear_minor=False,
        clear_major=False,
    )
    out = compose_clutter_mask_texture(env=None, plane=part)
    assert out is not None
    arr = np.asarray(out)
    assert (arr[..., 0] == 255).all()


def test_compose_returns_none_on_null_cluttermask() -> None:
    """No cluttermask → log a warning and return None (not a hard error,
    so the cull pass can keep going with whatever planes did resolve)."""
    part = _make_part(cluttermask_pid=0)  # null PPtr
    out = compose_clutter_mask_texture(env=None, plane=part)
    assert out is None
