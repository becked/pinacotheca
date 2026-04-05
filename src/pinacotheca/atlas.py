"""
Texture atlas generation for map rendering.

Packs extracted sprites into atlas images (WebP) with JSON manifests
for efficient GPU rendering in per-ankh's deck.gl map.
"""

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

# ---------------------------------------------------------------------------
# Hex mask geometry
# Derived from Old World's terrain sprite dimensions (211x181).
# These define a pointy-top elliptical hexagon that fits within the sprite
# canvas with ~1-3px margin. The renderer (per-ankh) uses complementary
# spacing values (199 horizontal, 132 vertical) to tile these with overlap.
# ---------------------------------------------------------------------------
HEX_RADIUS_X: int = 120  # Half hex width (~208px hex in 211px sprite)
HEX_RADIUS_Y: int = 88  # Half hex height (~176px hex in 181px sprite)
DILATION_ITERATIONS: int = 50  # Edge expansion passes before hex clipping
MAX_ATLAS_SIZE: int = 4096  # WebGL2 guaranteed max texture dimension


@dataclass(frozen=True)
class AtlasCategoryConfig:
    """Configuration for one atlas category."""

    category_dirs: list[str]
    """Extracted sprite directories to pull from (under sprites/)."""

    sprite_width: int
    """Target cell width in the atlas."""

    sprite_height: int
    """Target cell height in the atlas."""

    apply_hex_mask: bool = False
    """Whether to apply dilation + hex clipping (terrain/height only)."""

    name_mapping: dict[str, str] = field(default_factory=dict)
    """Optional rename map: extracted filename stem → atlas sprite name."""


ATLAS_CONFIGS: dict[str, AtlasCategoryConfig] = {
    "terrain": AtlasCategoryConfig(
        category_dirs=["terrains"],
        sprite_width=211,
        sprite_height=181,
        apply_hex_mask=True,
    ),
    "height": AtlasCategoryConfig(
        category_dirs=["heights"],
        sprite_width=211,
        sprite_height=181,
        apply_hex_mask=True,
        name_mapping={
            "HillsEditorIcon": "HEIGHT_HILL",
            "MountainEditorIcon": "HEIGHT_MOUNTAIN",
            "VolcanoEditorIcon": "HEIGHT_VOLCANO",
        },
    ),
    "improvement": AtlasCategoryConfig(
        category_dirs=["improvements"],
        sprite_width=200,
        sprite_height=200,
    ),
    "resource": AtlasCategoryConfig(
        category_dirs=["resources"],
        sprite_width=64,
        sprite_height=64,
    ),
    "specialist": AtlasCategoryConfig(
        category_dirs=["specialists"],
        sprite_width=128,
        sprite_height=128,
    ),
    "city": AtlasCategoryConfig(
        category_dirs=["crests", "city"],
        sprite_width=136,
        sprite_height=136,
    ),
}


# ---------------------------------------------------------------------------
# Hex masking pipeline
# ---------------------------------------------------------------------------


def _create_hex_mask(
    width: int,
    height: int,
    radius_x: float = HEX_RADIUS_X,
    radius_y: float = HEX_RADIUS_Y,
) -> Image.Image:
    """Create a pointy-top hexagonal mask as a grayscale image.

    The hex is centered on the image and defined by elliptical radii.
    """
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)

    cx = width / 2
    cy = height / 2

    # Pointy-top hex: vertices at 30° intervals starting from top
    points: list[tuple[float, float]] = []
    for i in range(6):
        angle = (math.pi / 3) * i - math.pi / 2  # start from top
        x = cx + radius_x * math.cos(angle)
        y = cy + radius_y * math.sin(angle)
        points.append((x, y))

    draw.polygon(points, fill=255)
    return mask


def _expand_edges(img_array: np.ndarray, iterations: int = DILATION_ITERATIONS) -> np.ndarray:
    """Expand opaque pixels into transparent areas via 4-directional dilation.

    Fills transparent pixels with RGB from their nearest opaque neighbor.
    This ensures that overlapping hex tiles show color instead of gaps.
    """
    result = img_array.copy()
    h, w = result.shape[:2]

    for _ in range(iterations):
        alpha = result[:, :, 3]
        transparent = alpha < 128

        for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            shifted_alpha = np.zeros_like(alpha)
            shifted_colors = np.zeros_like(result)

            if dy == -1:
                shifted_alpha[1:, :] = alpha[:-1, :]
                shifted_colors[1:, :] = result[:-1, :]
            elif dy == 1:
                shifted_alpha[:-1, :] = alpha[1:, :]
                shifted_colors[:-1, :] = result[1:, :]
            elif dx == -1:
                shifted_alpha[:, 1:] = alpha[:, :-1]
                shifted_colors[:, 1:] = result[:, :-1]
            elif dx == 1:
                shifted_alpha[:, :-1] = alpha[:, 1:]
                shifted_colors[:, :-1] = result[:, 1:]

            fill_mask = transparent & (shifted_alpha >= 128)
            result[fill_mask] = shifted_colors[fill_mask]

    return result


def _resize_to_canvas(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Resize image to fit target dimensions, centered on transparent canvas.

    Preserves aspect ratio using LANCZOS resampling.
    """
    scale = min(target_w / img.width, target_h / img.height)
    new_w = int(img.width * scale)
    new_h = int(img.height * scale)
    resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    offset_x = (target_w - new_w) // 2
    offset_y = (target_h - new_h) // 2
    canvas.paste(resized, (offset_x, offset_y))
    return canvas


def apply_hex_mask(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Resize a sprite and apply the hex masking pipeline.

    Steps:
    1. Resize to target dimensions (centered, aspect-preserving)
    2. Edge dilation — expand opaque pixels outward into transparent areas
    3. Hex clip — apply pointy-top elliptical hex mask as alpha channel
    """
    img = _resize_to_canvas(img, target_w, target_h)

    img_array = np.array(img)
    img_array = _expand_edges(img_array)

    mask = _create_hex_mask(target_w, target_h)
    img_array[:, :, 3] = np.array(mask)

    return Image.fromarray(img_array)


# ---------------------------------------------------------------------------
# Grid packing
# ---------------------------------------------------------------------------


def pack_atlas(
    sprites: dict[str, Image.Image],
    cell_width: int,
    cell_height: int,
) -> tuple[Image.Image, dict[str, dict[str, int]]]:
    """Pack uniformly-sized sprites into a grid atlas.

    Args:
        sprites: Mapping of sprite name → RGBA image (already resized to cell dims).
        cell_width: Width of each cell in the grid.
        cell_height: Height of each cell in the grid.

    Returns:
        Tuple of (atlas image, sprite manifest mapping name → {x, y, width, height}).

    Raises:
        ValueError: If the sprites don't fit within MAX_ATLAS_SIZE.
    """
    if not sprites:
        raise ValueError("No sprites to pack")

    names = sorted(sprites.keys())
    count = len(names)

    cols = MAX_ATLAS_SIZE // cell_width
    rows = math.ceil(count / cols)

    atlas_w = min(cols, count) * cell_width
    atlas_h = rows * cell_height

    if atlas_h > MAX_ATLAS_SIZE:
        raise ValueError(
            f"Atlas would be {atlas_w}x{atlas_h} which exceeds "
            f"{MAX_ATLAS_SIZE}x{MAX_ATLAS_SIZE} limit ({count} sprites at {cell_width}x{cell_height})"
        )

    atlas = Image.new("RGBA", (atlas_w, atlas_h), (0, 0, 0, 0))
    manifest: dict[str, dict[str, int]] = {}

    for i, name in enumerate(names):
        col = i % cols
        row = i // cols
        x = col * cell_width
        y = row * cell_height
        atlas.paste(sprites[name], (x, y))
        manifest[name] = {"x": x, "y": y, "width": cell_width, "height": cell_height}

    return atlas, manifest


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def generate_atlases(
    sprites_dir: Path,
    output_dir: Path,
    *,
    categories: list[str] | None = None,
    lossy_quality: int | None = None,
    verbose: bool = True,
) -> dict[str, int]:
    """Generate texture atlases from extracted sprites.

    Args:
        sprites_dir: Directory containing categorized sprite folders
            (e.g., ``extracted/sprites/``).
        output_dir: Where to write atlas WebP + JSON files.
        categories: Which atlas categories to generate (default: all).
        lossy_quality: If set, use lossy WebP at this quality (0-100).
            Default (None) uses lossless WebP.
        verbose: Print progress to stdout.

    Returns:
        Mapping of atlas category name → number of sprites packed.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    targets = categories or list(ATLAS_CONFIGS.keys())
    results: dict[str, int] = {}

    for cat_name in targets:
        config = ATLAS_CONFIGS.get(cat_name)
        if config is None:
            raise ValueError(
                f"Unknown atlas category '{cat_name}'. Valid categories: {', '.join(ATLAS_CONFIGS)}"
            )

        if verbose:
            print(f"Generating {cat_name} atlas...")

        # Collect sprite images from source directories
        sprites: dict[str, Image.Image] = {}
        for source_dir_name in config.category_dirs:
            source_dir = sprites_dir / source_dir_name
            if not source_dir.is_dir():
                if verbose:
                    print(f"  Warning: source directory not found: {source_dir}")
                continue

            for png_path in sorted(source_dir.glob("*.png")):
                stem = png_path.stem
                atlas_name = config.name_mapping.get(stem, stem)
                img = Image.open(png_path).convert("RGBA")

                if config.apply_hex_mask:
                    img = apply_hex_mask(img, config.sprite_width, config.sprite_height)
                else:
                    img = _resize_to_canvas(img, config.sprite_width, config.sprite_height)

                sprites[atlas_name] = img

        if not sprites:
            if verbose:
                print("  No sprites found, skipping.")
            continue

        # Pack and save
        atlas_image, sprite_manifest = pack_atlas(
            sprites, config.sprite_width, config.sprite_height
        )

        manifest = {
            "atlas": f"{cat_name}.webp",
            "cellWidth": config.sprite_width,
            "cellHeight": config.sprite_height,
            "sprites": sprite_manifest,
        }

        # Write WebP
        webp_path = output_dir / f"{cat_name}.webp"
        save_kwargs: dict[str, object] = {}
        if lossy_quality is not None:
            save_kwargs["quality"] = lossy_quality
            save_kwargs["method"] = 6  # best compression
        else:
            save_kwargs["lossless"] = True

        atlas_image.save(str(webp_path), "WEBP", **save_kwargs)

        # Write JSON manifest
        json_path = output_dir / f"{cat_name}.json"
        json_path.write_text(json.dumps(manifest, indent=2) + "\n")

        if verbose:
            print(
                f"  {len(sprites)} sprites → {atlas_image.width}x{atlas_image.height} "
                f"({webp_path.stat().st_size // 1024}KB)"
            )

        results[cat_name] = len(sprites)

    return results
