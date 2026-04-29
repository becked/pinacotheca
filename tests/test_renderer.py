"""Tests for renderer projection helpers."""

from __future__ import annotations

import numpy as np

from pinacotheca.renderer import orthographic_matrix


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
