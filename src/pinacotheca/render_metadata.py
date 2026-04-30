"""Per-render JSON metadata sidecars.

Every 3D render (improvements, resources, units, layered tiles) writes a
``<NAME>.json`` next to its ``<NAME>.png``. The sidecar exposes the
world-space bounding box of the rendered geometry, the camera framing
constants, and the world-units-per-output-pixel scale, so consumers can
recover absolute size and compose multiple prefabs at correct relative
scale.

Primary consumer: per-ankh (sister hex-map renderer). Per-ankh composites
a resource sprite over an improvement sprite for the same tile (deer over
Camp tents, herd over Pasture, ore over Mine). Today each PNG is rendered
tight to its own per-prefab bbox, so the relative scale on a tile is
wrong. The sidecar gives per-ankh ``maxExtent`` per prefab — the relative
scale falls out of ``R.maxExtent / I.maxExtent``.

Schema is versioned (``"version": 1``). Add fields freely; bump when a
field is removed or its semantics change.

See ``docs/extracting-3d-buildings.md`` (Metadata sidecar) for the full
contract.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

SCHEMA_VERSION = 1

Composition = Literal["prefab", "layered"]
Projection = Literal["orthographic", "perspective"]


@dataclass(frozen=True)
class GroundHexBounds:
    """World-space bbox of the layered hex ground plane (biome + PVT).

    Present only on layered renders. The mesh is a quad whose visual hex
    shape comes from the ``Hex_Mask`` alpha — this bbox is the underlying
    quad's axis-aligned extent, which is what consumers anchor a
    hex-clip region to. ``None`` on prefab renders.
    """

    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]


@dataclass(frozen=True)
class WorldBounds:
    """World-space bbox of the rendered geometry, in Unity world units."""

    max_extent: float
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]
    ground_hex: GroundHexBounds | None = None


@dataclass(frozen=True)
class FramingInfo:
    """Camera framing used for the render.

    ``frustum_half_size`` is set for orthographic projections (used for
    buildings/improvements/resources/layered). ``fov_deg`` is set for
    perspective projections (used for units when the mesh is upright or
    horizontal). Exactly one of the two is non-``None``.
    """

    projection: Projection
    tilt_deg: float | None
    distance: float
    frustum_half_size: float | None
    fov_deg: float | None


@dataclass(frozen=True)
class RenderInfo:
    """Render-output dimensions and the load-bearing world-per-pixel scale.

    ``world_units_per_output_pixel`` accounts for both the autocrop AND
    the LANCZOS upscale that ``autocrop_with_padding`` applies when
    cropped content is smaller than ``min_size``. Consumers should use
    this scalar (not infer pixels-per-unit from the pre-crop dims) for
    absolute pixel placement on a tile.
    """

    pre_crop_width_px: int
    pre_crop_height_px: int
    output_width_px: int
    output_height_px: int
    world_units_per_output_pixel: float


@dataclass(frozen=True)
class RenderMetadata:
    """Sidecar payload for a single rendered PNG."""

    version: int
    composition: Composition
    world: WorldBounds
    framing: FramingInfo
    render: RenderInfo

    def to_json_dict(self) -> dict[str, Any]:
        """Serialize to a camelCase JSON dict (matches gallery-filter style)."""
        return {
            "version": self.version,
            "composition": self.composition,
            "world": {
                "maxExtent": self.world.max_extent,
                "bboxMin": list(self.world.bbox_min),
                "bboxMax": list(self.world.bbox_max),
                "groundHex": (
                    None
                    if self.world.ground_hex is None
                    else {
                        "bboxMin": list(self.world.ground_hex.bbox_min),
                        "bboxMax": list(self.world.ground_hex.bbox_max),
                    }
                ),
            },
            "framing": {
                "projection": self.framing.projection,
                "tiltDeg": self.framing.tilt_deg,
                "distance": self.framing.distance,
                "frustumHalfSize": self.framing.frustum_half_size,
                "fovDeg": self.framing.fov_deg,
            },
            "render": {
                "preCropWidthPx": self.render.pre_crop_width_px,
                "preCropHeightPx": self.render.pre_crop_height_px,
                "outputWidthPx": self.render.output_width_px,
                "outputHeightPx": self.render.output_height_px,
                "worldUnitsPerOutputPixel": self.render.world_units_per_output_pixel,
            },
        }

    def with_composition(self, composition: Composition) -> RenderMetadata:
        """Return a copy with a different ``composition`` tag.

        Used by the layered orchestrator to override the buildings-layer
        metadata's default ``"prefab"`` to ``"layered"``.
        """
        return RenderMetadata(
            version=self.version,
            composition=composition,
            world=self.world,
            framing=self.framing,
            render=self.render,
        )

    def with_world(self, world: WorldBounds) -> RenderMetadata:
        """Return a copy with replaced world bounds."""
        return RenderMetadata(
            version=self.version,
            composition=self.composition,
            world=world,
            framing=self.framing,
            render=self.render,
        )

    def with_render(self, render: RenderInfo) -> RenderMetadata:
        """Return a copy with replaced render-info (output dims + scale)."""
        return RenderMetadata(
            version=self.version,
            composition=self.composition,
            world=self.world,
            framing=self.framing,
            render=render,
        )


def write_sidecar(png_path: Path, metadata: RenderMetadata) -> Path:
    """Write ``<png_path with .json suffix>`` next to the PNG.

    Always overwrites. Returns the path written.
    """
    json_path = png_path.with_suffix(".json")
    json_path.write_text(json.dumps(metadata.to_json_dict(), indent=2) + "\n")
    return json_path
