"""Synthetic-XML tests for terrain_index.

These tests build minimal terrain.xml + assetVariation.xml + asset.xml
fixtures in a tmp dir, then assert that load_terrain_tiles produces the
expected (biome, height) → prefab mappings — no real game files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pinacotheca.terrain_index import (
    LAND_HEIGHTS,
    TerrainTile,
    load_terrain_tiles,
)


def _write(path: Path, content: str) -> None:
    path.write_text(content)


def _wrap(entries: str) -> str:
    return f"<root>{entries}</root>"


# Helper to write the standard single-hex feature variations + their assets,
# which terrain_index hardcodes (ASSET_VARIATION_TILE_MOUNTAIN_1 /
# ASSET_VARIATION_TILE_VOLCANO_1). Tests that don't care about the feature
# layer can still call this so the warnings stay quiet.
_FEATURE_VARIATIONS = """
    <Entry>
        <zType>ASSET_VARIATION_TILE_MOUNTAIN_1</zType>
        <SingleAsset>ASSET_TERRAIN_TILE_MOUNTAIN_1</SingleAsset>
    </Entry>
    <Entry>
        <zType>ASSET_VARIATION_TILE_VOLCANO_1</zType>
        <SingleAsset>ASSET_TERRAIN_TILE_VOLCANO_1</SingleAsset>
    </Entry>
"""

_FEATURE_ASSETS = """
    <Entry>
        <zType>ASSET_TERRAIN_TILE_MOUNTAIN_1</zType>
        <zAsset>Prefabs/Terrain/Mountains/TileMountain</zAsset>
    </Entry>
    <Entry>
        <zType>ASSET_TERRAIN_TILE_VOLCANO_1</zType>
        <zAsset>Prefabs/Terrain/Volcanos/TileVolcano_1</zAsset>
    </Entry>
"""


def test_temperate_emits_four_heights(tmp_path: Path) -> None:
    """TEMPERATE × FLAT/HILL/MOUNTAIN/VOLCANO all resolve.

    FLAT and HILL each resolve through their own per-biome variation;
    MOUNTAIN and VOLCANO resolve through the hardcoded shared
    MOUNTAIN_1 / VOLCANO_1 variations (since terrain.xml's MOUNTAIN/VOLCANO
    pairs point back to FLAT). Ground is always TilePlains_01.
    """
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
                    <Pair>
                        <zIndex>HEIGHT_MOUNTAIN</zIndex>
                        <zValue>ASSET_VARIATION_TILE_TEMPERATE_FLAT</zValue>
                    </Pair>
                    <Pair>
                        <zIndex>HEIGHT_VOLCANO</zIndex>
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
            <Entry>
                <zType>ASSET_VARIATION_TILE_HILL_TEMPERATE</zType>
                <SingleAsset>ASSET_TERRAIN_TILE_HILL_TEMPERATE</SingleAsset>
            </Entry>
            """
            + _FEATURE_VARIATIONS
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
                <zType>ASSET_TERRAIN_TILE_HILL_TEMPERATE</zType>
                <zAsset>Prefabs/Terrain/Hills/HillsV2/HillsTemperate</zAsset>
            </Entry>
            """
            + _FEATURE_ASSETS
        ),
    )
    result = load_terrain_tiles(tmp_path)
    by_height = {tile.height: tile for tile in result}
    assert set(by_height) == set(LAND_HEIGHTS)
    assert by_height["FLAT"] == TerrainTile(
        biome="TEMPERATE",
        height="FLAT",
        output_name="TERRAIN_3D_TEMPERATE_FLAT",
        ground_prefab="TilePlains_01",
        feature_prefab=None,
        water_prefab=None,
    )
    assert by_height["HILL"].feature_prefab == "HillsTemperate"
    assert by_height["HILL"].ground_prefab == "TilePlains_01"
    assert by_height["MOUNTAIN"].feature_prefab == "TileMountain"
    assert by_height["MOUNTAIN"].ground_prefab == "TilePlains_01"
    assert by_height["VOLCANO"].feature_prefab == "TileVolcano_1"


def test_water_emits_three_water_prefabs(tmp_path: Path) -> None:
    """WATER × COAST/OCEAN/LAKE each resolves to its own water prefab; no
    biome ground is set."""
    _write(
        tmp_path / "terrain.xml",
        _wrap(
            """
            <Entry>
                <zType>TERRAIN_WATER</zType>
                <aeHeightAsset>
                    <Pair>
                        <zIndex>HEIGHT_COAST</zIndex>
                        <zValue>ASSET_VARIATION_TILE_COAST</zValue>
                    </Pair>
                    <Pair>
                        <zIndex>HEIGHT_OCEAN</zIndex>
                        <zValue>ASSET_VARIATION_TILE_OCEAN</zValue>
                    </Pair>
                    <Pair>
                        <zIndex>HEIGHT_LAKE</zIndex>
                        <zValue>ASSET_VARIATION_TILE_LAKE</zValue>
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
                <zType>ASSET_VARIATION_TILE_COAST</zType>
                <SingleAsset>ASSET_TERRAIN_TILE_COAST</SingleAsset>
            </Entry>
            <Entry>
                <zType>ASSET_VARIATION_TILE_OCEAN</zType>
                <SingleAsset>ASSET_TERRAIN_TILE_OCEAN</SingleAsset>
            </Entry>
            <Entry>
                <zType>ASSET_VARIATION_TILE_LAKE</zType>
                <SingleAsset>ASSET_TERRAIN_TILE_LAKE</SingleAsset>
            </Entry>
            """
            + _FEATURE_VARIATIONS
        ),
    )
    _write(
        tmp_path / "asset.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_TERRAIN_TILE_COAST</zType>
                <zAsset>Prefabs/Terrain/Coast/TileCoast</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_TERRAIN_TILE_OCEAN</zType>
                <zAsset>Prefabs/Terrain/Ocean/TileOcean</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_TERRAIN_TILE_LAKE</zType>
                <zAsset>Prefabs/Terrain/TileLake</zAsset>
            </Entry>
            """
            + _FEATURE_ASSETS
        ),
    )
    result = load_terrain_tiles(tmp_path)
    by_height = {tile.height: tile for tile in result}
    assert set(by_height) == {"COAST", "OCEAN", "LAKE"}
    assert by_height["COAST"].water_prefab == "TileCoast"
    assert by_height["OCEAN"].water_prefab == "TileOcean"
    assert by_height["LAKE"].water_prefab == "TileLake"
    for tile in result:
        assert tile.ground_prefab is None
        assert tile.feature_prefab is None
        assert tile.output_name == f"TERRAIN_3D_WATER_{tile.height}"


def test_urban_hill_collapses_to_flat(tmp_path: Path) -> None:
    """URBAN/HILL points to the same variation as URBAN/FLAT — emit only
    one URBAN tile (the FLAT one) to avoid a duplicate PNG."""
    _write(
        tmp_path / "terrain.xml",
        _wrap(
            """
            <Entry>
                <zType>TERRAIN_URBAN</zType>
                <aeHeightAsset>
                    <Pair>
                        <zIndex>HEIGHT_FLAT</zIndex>
                        <zValue>ASSET_VARIATION_TILE_URBAN_FLAT</zValue>
                    </Pair>
                    <Pair>
                        <zIndex>HEIGHT_HILL</zIndex>
                        <zValue>ASSET_VARIATION_TILE_URBAN_FLAT</zValue>
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
                <zType>ASSET_VARIATION_TILE_URBAN_FLAT</zType>
                <SingleAsset>ASSET_TERRAIN_TILE_URBAN_FLAT</SingleAsset>
            </Entry>
            """
            + _FEATURE_VARIATIONS
        ),
    )
    _write(
        tmp_path / "asset.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_TERRAIN_TILE_URBAN_FLAT</zType>
                <zAsset>Prefabs/Terrain/TileUrban</zAsset>
            </Entry>
            """
            + _FEATURE_ASSETS
        ),
    )
    result = load_terrain_tiles(tmp_path)
    assert len(result) == 1
    tile = result[0]
    assert tile.biome == "URBAN"
    assert tile.height == "FLAT"
    assert tile.output_name == "TERRAIN_3D_URBAN_FLAT"
    assert tile.ground_prefab == "TileUrban"
    assert tile.feature_prefab is None


def test_multi_hex_mountain_variants_not_picked(tmp_path: Path) -> None:
    """Even if 2/3/4/7-hex MOUNTAIN variations are present in the chain,
    terrain_index resolves only the single-hex MOUNTAIN_1 / VOLCANO_1 by
    name — multi-hex range pieces span multiple tiles and aren't usable as
    a single-tile icon."""
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
                        <zIndex>HEIGHT_MOUNTAIN</zIndex>
                        <zValue>ASSET_VARIATION_TILE_TEMPERATE_FLAT</zValue>
                    </Pair>
                </aeHeightAsset>
            </Entry>
            """
        ),
    )
    # Include multi-hex variations to verify they aren't picked even when
    # present in the chain.
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VARIATION_TILE_TEMPERATE_FLAT</zType>
                <SingleAsset>ASSET_TERRAIN_TILE_TEMPERATE_FLAT_01</SingleAsset>
            </Entry>
            <Entry>
                <zType>ASSET_VARIATION_TILE_MOUNTAIN_2</zType>
                <SingleAsset>ASSET_TERRAIN_TILE_MOUNTAIN_2</SingleAsset>
            </Entry>
            <Entry>
                <zType>ASSET_VARIATION_TILE_MOUNTAIN_7</zType>
                <SingleAsset>ASSET_TERRAIN_TILE_MOUNTAIN_7</SingleAsset>
            </Entry>
            """
            + _FEATURE_VARIATIONS
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
                <zType>ASSET_TERRAIN_TILE_MOUNTAIN_2</zType>
                <zAsset>Prefabs/Terrain/Mountains/Phase_02/TileMountain_2Hex_01</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_TERRAIN_TILE_MOUNTAIN_7</zType>
                <zAsset>Prefabs/Terrain/Mountains/Phase_02/TileMountain_7Hex_01</zAsset>
            </Entry>
            """
            + _FEATURE_ASSETS
        ),
    )
    result = load_terrain_tiles(tmp_path)
    mountain_tiles = [t for t in result if t.height == "MOUNTAIN"]
    assert len(mountain_tiles) == 1
    assert mountain_tiles[0].feature_prefab == "TileMountain"  # single-hex
    # Negative-assert against multi-hex paths.
    for tile in result:
        assert tile.feature_prefab != "TileMountain_2Hex_01"
        assert tile.feature_prefab != "TileMountain_7Hex_01"


def test_aiRandomAssets_picks_highest_weight(tmp_path: Path) -> None:
    """Variation with weighted random list — highest weight wins, mirroring
    the rule used by every other loader in asset_index.

    LUSH ships with three TileGrass_* candidates of equal-or-different
    weights; verify the max-weight candidate is selected.
    """
    _write(
        tmp_path / "terrain.xml",
        _wrap(
            """
            <Entry>
                <zType>TERRAIN_LUSH</zType>
                <aeHeightAsset>
                    <Pair>
                        <zIndex>HEIGHT_FLAT</zIndex>
                        <zValue>ASSET_VARIATION_TILE_LUSH_FLAT</zValue>
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
                <zType>ASSET_VARIATION_TILE_LUSH_FLAT</zType>
                <aiRandomAssets>
                    <Pair>
                        <zIndex>ASSET_TERRAIN_TILE_GRASS_01</zIndex>
                        <iValue>5</iValue>
                    </Pair>
                    <Pair>
                        <zIndex>ASSET_TERRAIN_TILE_GRASS_02</zIndex>
                        <iValue>20</iValue>
                    </Pair>
                    <Pair>
                        <zIndex>ASSET_TERRAIN_TILE_GRASS_03</zIndex>
                        <iValue>1</iValue>
                    </Pair>
                </aiRandomAssets>
            </Entry>
            """
            + _FEATURE_VARIATIONS
        ),
    )
    _write(
        tmp_path / "asset.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_TERRAIN_TILE_GRASS_01</zType>
                <zAsset>Prefabs/Terrain/TileGrass_01</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_TERRAIN_TILE_GRASS_02</zType>
                <zAsset>Prefabs/Terrain/TileGrass_02</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_TERRAIN_TILE_GRASS_03</zType>
                <zAsset>Prefabs/Terrain/TileGrass_03</zAsset>
            </Entry>
            """
            + _FEATURE_ASSETS
        ),
    )
    result = load_terrain_tiles(tmp_path)
    flat_tiles = [t for t in result if t.height == "FLAT" and t.biome == "LUSH"]
    assert len(flat_tiles) == 1
    assert flat_tiles[0].ground_prefab == "TileGrass_02"


def test_broken_chain_drops_tile(tmp_path: Path) -> None:
    """A biome whose FLAT chain breaks (variation absent) emits no tiles —
    we don't synthesize a partial ground."""
    _write(
        tmp_path / "terrain.xml",
        _wrap(
            """
            <Entry>
                <zType>TERRAIN_MARSH</zType>
                <aeHeightAsset>
                    <Pair>
                        <zIndex>HEIGHT_FLAT</zIndex>
                        <zValue>ASSET_VARIATION_TILE_MARSH_FLAT</zValue>
                    </Pair>
                </aeHeightAsset>
            </Entry>
            """
        ),
    )
    # No variation entry for MARSH_FLAT — chain breaks.
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(_FEATURE_VARIATIONS),
    )
    _write(tmp_path / "asset.xml", _wrap(_FEATURE_ASSETS))
    result = load_terrain_tiles(tmp_path)
    assert result == []


def test_missing_xml_dir_returns_empty(tmp_path: Path) -> None:
    """A non-existent xml_dir returns [] without raising — matches every
    other loader's behavior."""
    assert load_terrain_tiles(tmp_path / "nope") == []


def test_real_xml_chain_resolves_28_tiles() -> None:
    """Smoke test against the real Reference/XML/Infos directory if the
    symlink is present. Skipped on CI / machines without the game install.

    Confirms the (biome, height) coverage matches the documented set:
    6 land × 4 + 1 URBAN + 3 WATER = 28.
    """
    xml_dir = Path(__file__).parent.parent / "reference" / "XML" / "Infos"
    if not xml_dir.exists():
        pytest.skip("Reference symlink not present")
    result = load_terrain_tiles(xml_dir)
    by_biome: dict[str, set[str]] = {}
    for tile in result:
        by_biome.setdefault(tile.biome, set()).add(tile.height)
    assert by_biome.get("TEMPERATE") == {"FLAT", "HILL", "MOUNTAIN", "VOLCANO"}
    assert by_biome.get("LUSH") == {"FLAT", "HILL", "MOUNTAIN", "VOLCANO"}
    assert by_biome.get("ARID") == {"FLAT", "HILL", "MOUNTAIN", "VOLCANO"}
    assert by_biome.get("SAND") == {"FLAT", "HILL", "MOUNTAIN", "VOLCANO"}
    assert by_biome.get("TUNDRA") == {"FLAT", "HILL", "MOUNTAIN", "VOLCANO"}
    assert by_biome.get("MARSH") == {"FLAT", "HILL", "MOUNTAIN", "VOLCANO"}
    assert by_biome.get("URBAN") == {"FLAT"}
    assert by_biome.get("WATER") == {"COAST", "OCEAN", "LAKE"}
    assert len(result) == 28
