"""Synthetic-XML tests for biome_base's terrain-chain resolver.

The full `load_biome_base` end-to-end requires a UnityPy environment, so
these tests cover the XML-only resolver `_resolve_flat_prefab_name` —
the bit that's pure-Python and needs CI coverage. The UnityPy-dependent
half is exercised via the live-data smoke during extraction.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pinacotheca.biome_base import _resolve_flat_prefab_name


def _write(path: Path, content: str) -> None:
    path.write_text(content)


def _wrap(entries: str) -> str:
    return f"<root>{entries}</root>"


def test_resolves_temperate_chain(tmp_path: Path) -> None:
    """Happy path: terrain → HEIGHT_FLAT → variation → highest-weight asset →
    prefab name."""
    _write(
        tmp_path / "terrain.xml",
        _wrap(
            """
            <Entry>
                <zType>TERRAIN_TEMPERATE</zType>
                <aeHeightAsset>
                    <Pair>
                        <zIndex>HEIGHT_FLAT</zIndex>
                        <zValue>ASSET_VARIATION_TILE_TEMPERATE_FLAT</zValue>
                    </Pair>
                    <Pair>
                        <zIndex>HEIGHT_HILL</zIndex>
                        <zValue>ASSET_VARIATION_TILE_HILL_TEMPERATE</zValue>
                    </Pair>
                </aeHeightAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VARIATION_TILE_TEMPERATE_FLAT</zType>
                <aiRandomAssets>
                    <Pair>
                        <zIndex>ASSET_TERRAIN_TILE_TEMPERATE_FLAT_01</zIndex>
                        <iValue>50</iValue>
                    </Pair>
                    <Pair>
                        <zIndex>ASSET_TERRAIN_TILE_TEMPERATE_FLAT_02</zIndex>
                        <iValue>30</iValue>
                    </Pair>
                </aiRandomAssets>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "asset.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_TERRAIN_TILE_TEMPERATE_FLAT_01</zType>
                <zAsset>Prefabs/Terrain/TilePlains_01</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_TERRAIN_TILE_TEMPERATE_FLAT_02</zType>
                <zAsset>Prefabs/Terrain/TilePlains_02</zAsset>
            </Entry>
            """
        ),
    )
    assert _resolve_flat_prefab_name(tmp_path, "TERRAIN_TEMPERATE") == "TilePlains_01"


def test_missing_terrain_raises(tmp_path: Path) -> None:
    """A bogus terrain_z_type fails loudly — no silent fallback."""
    _write(tmp_path / "terrain.xml", _wrap(""))
    with pytest.raises(RuntimeError, match="HEIGHT_FLAT pair missing"):
        _resolve_flat_prefab_name(tmp_path, "TERRAIN_TEMPERATE")


def test_missing_height_flat_raises(tmp_path: Path) -> None:
    """An entry without a HEIGHT_FLAT pair fails loudly."""
    _write(
        tmp_path / "terrain.xml",
        _wrap(
            """
            <Entry>
                <zType>TERRAIN_TEMPERATE</zType>
                <aeHeightAsset>
                    <Pair>
                        <zIndex>HEIGHT_HILL</zIndex>
                        <zValue>ASSET_VARIATION_TILE_HILL_TEMPERATE</zValue>
                    </Pair>
                </aeHeightAsset>
            </Entry>
            """
        ),
    )
    with pytest.raises(RuntimeError, match="HEIGHT_FLAT pair missing"):
        _resolve_flat_prefab_name(tmp_path, "TERRAIN_TEMPERATE")


def test_missing_variation_raises(tmp_path: Path) -> None:
    """Variation referenced by terrain.xml not found in assetVariation.xml."""
    _write(
        tmp_path / "terrain.xml",
        _wrap(
            """
            <Entry>
                <zType>TERRAIN_TEMPERATE</zType>
                <aeHeightAsset>
                    <Pair>
                        <zIndex>HEIGHT_FLAT</zIndex>
                        <zValue>ASSET_VARIATION_TILE_TEMPERATE_FLAT</zValue>
                    </Pair>
                </aeHeightAsset>
            </Entry>
            """
        ),
    )
    _write(tmp_path / "assetVariation.xml", _wrap(""))
    with pytest.raises(RuntimeError, match="AssetVariation .* not found"):
        _resolve_flat_prefab_name(tmp_path, "TERRAIN_TEMPERATE")


def test_missing_asset_raises(tmp_path: Path) -> None:
    """Asset referenced by the variation isn't in asset.xml."""
    _write(
        tmp_path / "terrain.xml",
        _wrap(
            """
            <Entry>
                <zType>TERRAIN_TEMPERATE</zType>
                <aeHeightAsset>
                    <Pair>
                        <zIndex>HEIGHT_FLAT</zIndex>
                        <zValue>ASSET_VARIATION_TILE_TEMPERATE_FLAT</zValue>
                    </Pair>
                </aeHeightAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VARIATION_TILE_TEMPERATE_FLAT</zType>
                <SingleAsset>ASSET_TERRAIN_TILE_TEMPERATE_FLAT_01</SingleAsset>
            </Entry>
            """
        ),
    )
    _write(tmp_path / "asset.xml", _wrap(""))
    with pytest.raises(RuntimeError, match="did not resolve to a prefab"):
        _resolve_flat_prefab_name(tmp_path, "TERRAIN_TEMPERATE")
