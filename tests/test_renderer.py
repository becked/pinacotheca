"""Tests for renderer projection helpers."""

from __future__ import annotations

import numpy as np
import pytest

from pinacotheca.renderer import orthographic_matrix, render_mesh_to_image


def test_orthographic_matrix_unit_box() -> None:
    """A symmetric ortho frustum produces the canonical OpenGL matrix.

    For (-1, 1, -1, 1, 0.1, 100) the diagonal scale terms are 2/2=1 on
    X/Y, -2/(100-0.1) on Z, and the only non-zero translation is the Z
    offset -(100+0.1)/(100-0.1). Right- and top-clip are at +1; the
    left/bottom translations cancel to zero.
    """
    m = orthographic_matrix(-1.0, 1.0, -1.0, 1.0, 0.1, 100.0)
    expected = np.array(
        [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, -2 / 99.9, -100.1 / 99.9],
            [0.0, 0.0, 0.0, 1.0],
        ],
        dtype="f4",
    )
    np.testing.assert_allclose(m, expected, rtol=1e-6, atol=1e-7)


def test_orthographic_matrix_preserves_xz_spacing() -> None:
    """Two camera-space points at different depth (z) but identical X
    project to the SAME NDC X. This is the property that prevents
    depth-crunch — a perspective matrix would NOT preserve this."""
    m = orthographic_matrix(-2.0, 2.0, -2.0, 2.0, 0.1, 100.0)
    # Two points at the same X but different camera-space Z (one closer,
    # one farther from camera). In view space the camera looks down -Z,
    # so "behind the camera" is +Z.
    near_pt = np.array([0.5, 0.0, -1.0, 1.0])
    far_pt = np.array([0.5, 0.0, -50.0, 1.0])
    near_clip = m @ near_pt
    far_clip = m @ far_pt
    # Ortho's bottom-row is [0,0,0,1] so w stays 1: NDC = clip directly.
    assert near_clip[3] == 1.0
    assert far_clip[3] == 1.0
    # NDC X is identical regardless of depth.
    np.testing.assert_allclose(near_clip[0], far_clip[0], atol=1e-6)
    # And it's proportional to input X (here 0.5 with half-width 2 → 0.25).
    np.testing.assert_allclose(near_clip[0], 0.25, atol=1e-6)


def _solid_texture():
    """1×1 white texture — enough for the renderer to bind a sampler."""
    from PIL import Image

    return Image.new("RGBA", (1, 1), (255, 255, 255, 255))


def _unit_quad_obj() -> str:
    """A small horizontal quad at y=0 spanning [-1, 1] in X and Z.

    Winding is reversed (3-2-1, 4-3-1) so the camera sees the front face
    under OpenGL's CCW convention with CULL_FACE enabled — matches what
    `bake_to_obj` emits for prefab parts viewed from above.
    """
    return (
        "v -1 0 -1\n"
        "v  1 0 -1\n"
        "v  1 0  1\n"
        "v -1 0  1\n"
        "vt 0 0\n"
        "vt 1 0\n"
        "vt 1 1\n"
        "vt 0 1\n"
        "vn 0 1 0\n"
        "vn 0 1 0\n"
        "vn 0 1 0\n"
        "vn 0 1 0\n"
        "f 3/3/3 2/2/2 1/1/1\n"
        "f 4/4/4 3/3/3 1/1/1\n"
    )


def _opengl_available() -> bool:
    try:
        import moderngl  # noqa: F401

        ctx = moderngl.create_standalone_context()
        ctx.release()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _opengl_available(), reason="headless OpenGL context unavailable")
def test_bbox_override_shrinks_the_footprint() -> None:
    """A render with `bbox_override` set to 4× the mesh's natural extent
    frames the camera around a much larger box, so the quad's pixel
    footprint shrinks. Without the override the same mesh fills more of
    the frame.
    """
    obj = _unit_quad_obj()
    tex = _solid_texture()

    no_override, _ = render_mesh_to_image(
        obj, tex, width=256, height=256, autocrop=False, force_upright=True
    )
    big_bbox = (
        np.array([-4.0, 0.0, -4.0]),
        np.array([4.0, 0.0, 4.0]),
    )
    overridden, _ = render_mesh_to_image(
        obj,
        tex,
        width=256,
        height=256,
        autocrop=False,
        force_upright=True,
        bbox_override=big_bbox,
    )

    no_override_arr = np.asarray(no_override.convert("RGBA"))
    overridden_arr = np.asarray(overridden.convert("RGBA"))

    no_override_pixels = int((no_override_arr[..., 3] > 0).sum())
    overridden_pixels = int((overridden_arr[..., 3] > 0).sum())

    # The 4×-larger bbox should produce a much smaller mesh footprint.
    assert overridden_pixels > 0  # quad still visible
    assert overridden_pixels < no_override_pixels // 2
