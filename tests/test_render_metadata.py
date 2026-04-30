"""Tests for render_metadata.py — the per-render JSON sidecar payload."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from pinacotheca.render_metadata import (
    SCHEMA_VERSION,
    FramingInfo,
    RenderInfo,
    RenderMetadata,
    WorldBounds,
    write_sidecar,
)
from pinacotheca.renderer import autocrop_with_padding


def _ortho_metadata() -> RenderMetadata:
    return RenderMetadata(
        version=SCHEMA_VERSION,
        composition="prefab",
        world=WorldBounds(
            max_extent=2.0,
            bbox_min=(-1.0, 0.0, -1.0),
            bbox_max=(1.0, 1.5, 1.0),
        ),
        framing=FramingInfo(
            projection="orthographic",
            tilt_deg=30.0,
            distance=3.2,
            frustum_half_size=1.32,
            fov_deg=None,
        ),
        render=RenderInfo(
            pre_crop_width_px=2048,
            pre_crop_height_px=2048,
            output_width_px=512,
            output_height_px=480,
            world_units_per_output_pixel=0.00516,
        ),
    )


class TestToJsonDict:
    def test_camelcase_keys(self) -> None:
        meta = _ortho_metadata()
        d = meta.to_json_dict()
        # Top-level keys
        assert set(d.keys()) == {"version", "composition", "world", "framing", "render"}
        # World subkeys are camelCase, not snake_case
        assert set(d["world"].keys()) == {"maxExtent", "bboxMin", "bboxMax"}
        assert set(d["framing"].keys()) == {
            "projection",
            "tiltDeg",
            "distance",
            "frustumHalfSize",
            "fovDeg",
        }
        assert set(d["render"].keys()) == {
            "preCropWidthPx",
            "preCropHeightPx",
            "outputWidthPx",
            "outputHeightPx",
            "worldUnitsPerOutputPixel",
        }

    def test_bbox_serialized_as_list(self) -> None:
        meta = _ortho_metadata()
        d = meta.to_json_dict()
        # JSON has no tuple type — bbox_min/max should be lists.
        assert isinstance(d["world"]["bboxMin"], list)
        assert d["world"]["bboxMin"] == [-1.0, 0.0, -1.0]
        assert d["world"]["bboxMax"] == [1.0, 1.5, 1.0]

    def test_perspective_metadata_uses_fov(self) -> None:
        meta = RenderMetadata(
            version=SCHEMA_VERSION,
            composition="prefab",
            world=WorldBounds(max_extent=2.0, bbox_min=(0.0, 0.0, 0.0), bbox_max=(2.0, 2.0, 2.0)),
            framing=FramingInfo(
                projection="perspective",
                tilt_deg=None,
                distance=3.0,
                frustum_half_size=None,
                fov_deg=60.0,
            ),
            render=RenderInfo(
                pre_crop_width_px=2048,
                pre_crop_height_px=2048,
                output_width_px=2048,
                output_height_px=2048,
                world_units_per_output_pixel=0.00169,
            ),
        )
        d = meta.to_json_dict()
        assert d["framing"]["projection"] == "perspective"
        assert d["framing"]["fovDeg"] == 60.0
        assert d["framing"]["frustumHalfSize"] is None
        assert d["framing"]["tiltDeg"] is None

    def test_round_trip_via_json(self) -> None:
        meta = _ortho_metadata()
        s = json.dumps(meta.to_json_dict())
        d = json.loads(s)
        assert d["world"]["maxExtent"] == 2.0
        assert d["render"]["worldUnitsPerOutputPixel"] == 0.00516

    def test_schema_version_stable(self) -> None:
        # If this fails on a content change you've forgotten to bump
        # SCHEMA_VERSION; both must move together when the contract breaks.
        assert SCHEMA_VERSION == 1


class TestWithers:
    def test_with_composition(self) -> None:
        meta = _ortho_metadata().with_composition("layered")
        assert meta.composition == "layered"
        # Other fields preserved
        assert meta.world.max_extent == 2.0

    def test_with_world(self) -> None:
        meta = _ortho_metadata().with_world(
            WorldBounds(max_extent=5.0, bbox_min=(-2.5, 0.0, -2.5), bbox_max=(2.5, 1.0, 2.5))
        )
        assert meta.world.max_extent == 5.0
        # Composition unchanged
        assert meta.composition == "prefab"

    def test_with_render(self) -> None:
        meta = _ortho_metadata().with_render(
            RenderInfo(
                pre_crop_width_px=2048,
                pre_crop_height_px=2048,
                output_width_px=256,
                output_height_px=256,
                world_units_per_output_pixel=0.01,
            )
        )
        assert meta.render.output_width_px == 256
        assert meta.render.world_units_per_output_pixel == 0.01


class TestWriteSidecar:
    def test_writes_next_to_png(self, tmp_path: Path) -> None:
        png = tmp_path / "FOO.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n")  # not a valid image, just a stub
        out = write_sidecar(png, _ortho_metadata())
        assert out == tmp_path / "FOO.json"
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["version"] == SCHEMA_VERSION
        assert data["composition"] == "prefab"

    def test_overwrites(self, tmp_path: Path) -> None:
        png = tmp_path / "FOO.png"
        png.write_bytes(b"")
        sidecar = png.with_suffix(".json")
        sidecar.write_text("garbage")
        write_sidecar(png, _ortho_metadata())
        data = json.loads(sidecar.read_text())
        assert data["world"]["maxExtent"] == 2.0


class TestAutocropReturnsCroppedDims:
    """The renderer relies on autocrop_with_padding's second return value
    to compute worldUnitsPerOutputPixel correctly when the LANCZOS upscale
    kicks in. These tests pin that contract.
    """

    def test_no_content_returns_original(self) -> None:
        from PIL import Image

        img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))  # fully transparent
        out, dims = autocrop_with_padding(img)
        # Empty bbox → return the input untouched
        assert out is img
        assert dims == (256, 256)

    def test_crop_without_upscale_returns_post_crop_dims(self) -> None:
        from PIL import Image

        img = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
        # Paint a 600x600 opaque block — much larger than min_size, so no
        # upscale will happen.
        block = Image.new("RGBA", (600, 600), (255, 0, 0, 255))
        img.paste(block, (200, 200))
        out, cropped_dims = autocrop_with_padding(img, padding=0)
        # No upscale — output dims equal cropped_dims.
        assert out.size == cropped_dims
        # Cropped should be exactly 600x600 (no padding).
        assert cropped_dims == (600, 600)

    def test_crop_with_upscale_returns_pre_upscale_dims(self) -> None:
        from PIL import Image

        img = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
        # 50x50 block — well below min_size=256, will trigger LANCZOS upscale.
        block = Image.new("RGBA", (50, 50), (0, 255, 0, 255))
        img.paste(block, (500, 500))
        out, cropped_dims = autocrop_with_padding(img, padding=0)
        # Pre-upscale crop is 50x50; output is upscaled to 256 on the larger axis.
        assert cropped_dims == (50, 50)
        assert max(out.size) == 256
        # Output dims differ from cropped_dims — this is exactly the case
        # where the renderer needs both to compute the correct
        # world-units-per-output-pixel.
        assert out.size != cropped_dims


def _opengl_available() -> bool:
    try:
        import moderngl  # noqa: F401

        ctx = moderngl.create_standalone_context()
        ctx.release()
        return True
    except Exception:
        return False


def _solid_texture():
    from PIL import Image

    return Image.new("RGBA", (1, 1), (255, 255, 255, 255))


def _unit_quad_obj() -> str:
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


@pytest.mark.skipif(not _opengl_available(), reason="headless OpenGL context unavailable")
class TestRenderMeshToImageReturnsMetadata:
    """End-to-end: the renderer returns a metadata payload whose framing
    and bbox match the mesh it rendered. Skipped when no headless GL.
    """

    def test_force_upright_metadata_is_orthographic(self) -> None:
        from pinacotheca.renderer import render_mesh_to_image

        img, meta = render_mesh_to_image(
            _unit_quad_obj(),
            _solid_texture(),
            width=512,
            height=512,
            autocrop=False,
            force_upright=True,
        )
        assert meta.composition == "prefab"
        assert meta.framing.projection == "orthographic"
        assert meta.framing.tilt_deg == 30.0
        assert meta.framing.fov_deg is None
        assert meta.framing.frustum_half_size is not None
        # Quad spans 2 units on X and Z, 0 on Y → max_extent = 2.0
        assert meta.world.max_extent == pytest.approx(2.0, abs=1e-6)
        # bbox covers the quad
        np.testing.assert_allclose(meta.world.bbox_min, (-1.0, 0.0, -1.0), atol=1e-6)
        np.testing.assert_allclose(meta.world.bbox_max, (1.0, 0.0, 1.0), atol=1e-6)
        # frustum_half_size = max_extent * 0.66
        assert meta.framing.frustum_half_size == pytest.approx(1.32, abs=1e-6)
        # No autocrop → output dims equal pre-crop dims
        assert meta.render.output_width_px == 512
        assert meta.render.output_height_px == 512
        # pre_crop_units_per_pixel = (2 * 1.32) / 512
        assert meta.render.world_units_per_output_pixel == pytest.approx(
            (2.0 * 1.32) / 512, rel=1e-5
        )
        # Image is what render returns; sanity-check it's a PIL image
        assert img.size == (512, 512)
