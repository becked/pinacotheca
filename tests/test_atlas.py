"""Tests for texture atlas generation."""

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from pinacotheca.atlas import (
    ATLAS_CONFIGS,
    MAX_ATLAS_SIZE,
    _create_hex_mask,
    _expand_edges,
    _resize_to_canvas,
    apply_hex_mask,
    generate_atlases,
    pack_atlas,
)


def _make_sprite(
    width: int = 64, height: int = 64, color: tuple[int, ...] = (255, 0, 0, 255)
) -> Image.Image:
    """Create a solid-color test sprite."""
    return Image.new("RGBA", (width, height), color)


class TestHexMask:
    """Tests for the hex masking pipeline."""

    def test_create_hex_mask_dimensions(self) -> None:
        mask = _create_hex_mask(211, 181)
        assert mask.size == (211, 181)
        assert mask.mode == "L"

    def test_create_hex_mask_center_white(self) -> None:
        mask = _create_hex_mask(211, 181)
        center = mask.getpixel((105, 90))
        assert center == 255

    def test_create_hex_mask_corners_black(self) -> None:
        mask = _create_hex_mask(211, 181)
        assert mask.getpixel((0, 0)) == 0
        assert mask.getpixel((210, 0)) == 0
        assert mask.getpixel((0, 180)) == 0
        assert mask.getpixel((210, 180)) == 0

    def test_apply_hex_mask_output_dimensions(self) -> None:
        img = _make_sprite(200, 170)
        result = apply_hex_mask(img, 211, 181)
        assert result.size == (211, 181)
        assert result.mode == "RGBA"

    def test_apply_hex_mask_corners_transparent(self) -> None:
        img = _make_sprite(211, 181)
        result = apply_hex_mask(img, 211, 181)
        arr = np.array(result)
        assert arr[0, 0, 3] == 0
        assert arr[0, 210, 3] == 0
        assert arr[180, 0, 3] == 0
        assert arr[180, 210, 3] == 0

    def test_apply_hex_mask_center_opaque(self) -> None:
        img = _make_sprite(211, 181)
        result = apply_hex_mask(img, 211, 181)
        arr = np.array(result)
        assert arr[90, 105, 3] == 255

    def test_resize_to_canvas_preserves_aspect(self) -> None:
        img = _make_sprite(100, 50)
        result = _resize_to_canvas(img, 200, 200)
        assert result.size == (200, 200)
        # The actual image content should be centered, with transparent above/below
        arr = np.array(result)
        # Top row should be transparent (padding)
        assert arr[0, 100, 3] == 0
        # Center should be opaque
        assert arr[100, 100, 3] == 255


class TestExpandEdges:
    """Tests for edge dilation."""

    def test_expands_into_transparent(self) -> None:
        # Create a 10x10 image with one opaque pixel in the center
        arr = np.zeros((10, 10, 4), dtype=np.uint8)
        arr[5, 5] = [255, 0, 0, 255]

        result = _expand_edges(arr, iterations=3)

        # The opaque pixel should have expanded outward
        assert result[5, 5, 3] >= 128  # center still opaque
        assert result[4, 5, 3] >= 128  # expanded up
        assert result[5, 6, 3] >= 128  # expanded right

    def test_preserves_existing_opaque(self) -> None:
        arr = np.zeros((10, 10, 4), dtype=np.uint8)
        arr[5, 5] = [255, 0, 0, 255]
        arr[5, 6] = [0, 255, 0, 255]

        result = _expand_edges(arr, iterations=1)

        # Original pixels should keep their colors
        assert result[5, 5, 0] == 255  # red
        assert result[5, 6, 1] == 255  # green


class TestPackAtlas:
    """Tests for grid packing."""

    def test_basic_packing(self) -> None:
        sprites = {f"sprite_{i}": _make_sprite() for i in range(4)}
        atlas, manifest = pack_atlas(sprites, 64, 64)

        assert len(manifest) == 4
        # 4 sprites at 64px wide: should fit in one row (4*64=256 < 4096)
        assert atlas.width == 256
        assert atlas.height == 64

    def test_manifest_coordinates(self) -> None:
        sprites = {"a": _make_sprite(), "b": _make_sprite(), "c": _make_sprite()}
        _, manifest = pack_atlas(sprites, 64, 64)

        # Sorted order: a, b, c
        assert manifest["a"] == {"x": 0, "y": 0, "width": 64, "height": 64}
        assert manifest["b"] == {"x": 64, "y": 0, "width": 64, "height": 64}
        assert manifest["c"] == {"x": 128, "y": 0, "width": 64, "height": 64}

    def test_deterministic_order(self) -> None:
        sprites = {f"z_{i}": _make_sprite() for i in range(10)}
        _, m1 = pack_atlas(sprites, 64, 64)
        _, m2 = pack_atlas(sprites, 64, 64)
        assert m1 == m2

    def test_wraps_to_multiple_rows(self) -> None:
        # 4096 / 200 = 20 cols. 25 sprites → 2 rows
        sprites = {f"s_{i:02d}": _make_sprite(200, 200) for i in range(25)}
        atlas, manifest = pack_atlas(sprites, 200, 200)

        assert atlas.width == 4000  # 20 * 200
        assert atlas.height == 400  # 2 * 200
        assert len(manifest) == 25

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="No sprites"):
            pack_atlas({}, 64, 64)

    def test_within_size_limit(self) -> None:
        # 132 improvement sprites at 200x200
        sprites = {f"imp_{i:03d}": _make_sprite(200, 200) for i in range(132)}
        atlas, _ = pack_atlas(sprites, 200, 200)
        assert atlas.width <= MAX_ATLAS_SIZE
        assert atlas.height <= MAX_ATLAS_SIZE


class TestNameMapping:
    """Tests for height sprite name mapping in config."""

    def test_height_config_has_mapping(self) -> None:
        config = ATLAS_CONFIGS["height"]
        assert config.name_mapping == {
            "HillsEditorIcon": "HEIGHT_HILL",
            "MountainEditorIcon": "HEIGHT_MOUNTAIN",
            "VolcanoEditorIcon": "HEIGHT_VOLCANO",
        }

    def test_other_configs_no_mapping(self) -> None:
        for name, config in ATLAS_CONFIGS.items():
            if name != "height":
                assert config.name_mapping == {}, f"{name} should have no name mapping"


class TestGenerateAtlases:
    """Integration tests for atlas generation."""

    def test_generates_webp_and_json(self, tmp_path: Path) -> None:
        # Set up fake sprite directory
        sprites_dir = tmp_path / "sprites"
        terrain_dir = sprites_dir / "terrains"
        terrain_dir.mkdir(parents=True)

        for name in ["TERRAIN_ARID", "TERRAIN_LUSH", "TERRAIN_SAND"]:
            _make_sprite(211, 181).save(terrain_dir / f"{name}.png")

        output_dir = tmp_path / "atlases"
        results = generate_atlases(sprites_dir, output_dir, categories=["terrain"], verbose=False)

        assert results == {"terrain": 3}
        assert (output_dir / "terrain.webp").exists()
        assert (output_dir / "terrain.json").exists()

        # Verify WebP is valid
        img = Image.open(output_dir / "terrain.webp")
        assert img.mode == "RGBA"

        # Verify JSON manifest
        manifest = json.loads((output_dir / "terrain.json").read_text())
        assert manifest["atlas"] == "terrain.webp"
        assert manifest["cellWidth"] == 211
        assert manifest["cellHeight"] == 181
        assert len(manifest["sprites"]) == 3
        assert "TERRAIN_ARID" in manifest["sprites"]

    def test_name_mapping_in_manifest(self, tmp_path: Path) -> None:
        sprites_dir = tmp_path / "sprites"
        heights_dir = sprites_dir / "heights"
        heights_dir.mkdir(parents=True)

        for name in ["HillsEditorIcon", "MountainEditorIcon", "VolcanoEditorIcon"]:
            _make_sprite(188, 151).save(heights_dir / f"{name}.png")

        output_dir = tmp_path / "atlases"
        results = generate_atlases(sprites_dir, output_dir, categories=["height"], verbose=False)

        assert results == {"height": 3}
        manifest = json.loads((output_dir / "height.json").read_text())
        assert "HEIGHT_HILL" in manifest["sprites"]
        assert "HEIGHT_MOUNTAIN" in manifest["sprites"]
        assert "HEIGHT_VOLCANO" in manifest["sprites"]
        assert "HillsEditorIcon" not in manifest["sprites"]

    def test_lossy_webp(self, tmp_path: Path) -> None:
        sprites_dir = tmp_path / "sprites"
        res_dir = sprites_dir / "resources"
        res_dir.mkdir(parents=True)

        _make_sprite(64, 64).save(res_dir / "RESOURCE_IRON.png")

        output_dir = tmp_path / "atlases"
        generate_atlases(
            sprites_dir, output_dir, categories=["resource"], lossy_quality=90, verbose=False
        )

        assert (output_dir / "resource.webp").exists()

    def test_missing_source_dir_skips(self, tmp_path: Path) -> None:
        sprites_dir = tmp_path / "sprites"
        sprites_dir.mkdir()

        output_dir = tmp_path / "atlases"
        results = generate_atlases(sprites_dir, output_dir, categories=["terrain"], verbose=False)

        assert results == {}

    def test_invalid_category_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Unknown atlas category"):
            generate_atlases(tmp_path, tmp_path, categories=["bogus"], verbose=False)


class TestAtlasConfigs:
    """Tests for atlas configuration completeness."""

    def test_all_configs_have_valid_dimensions(self) -> None:
        for name, config in ATLAS_CONFIGS.items():
            assert config.sprite_width > 0, f"{name} has invalid width"
            assert config.sprite_height > 0, f"{name} has invalid height"

    def test_hex_mask_only_on_terrain_and_height(self) -> None:
        for name, config in ATLAS_CONFIGS.items():
            if name in ("terrain", "height"):
                assert config.apply_hex_mask, f"{name} should have hex mask"
            else:
                assert not config.apply_hex_mask, f"{name} should not have hex mask"
