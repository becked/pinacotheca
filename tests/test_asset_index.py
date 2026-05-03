"""Synthetic-XML tests for asset_index.

These tests use temporary directories with hand-written XML strings —
no real game files. They verify the chain resolution semantics so we
don't depend on the game install for CI.
"""

from __future__ import annotations

from pathlib import Path

from pinacotheca.asset_index import (
    ImprovementAsset,
    UrbanRenderableImprovement,
    VegetationAsset,
    load_capital_assets,
    load_improvement_assets,
    load_resource_assets,
    load_urban_assets,
    load_urban_renderable_improvements,
    load_vegetation_assets,
)


def _write(path: Path, content: str) -> None:
    path.write_text(content)


def _wrap(entries: str) -> str:
    return f"<root>{entries}</root>"


def test_single_asset_chain_resolves(tmp_path: Path) -> None:
    """The happy path: improvement → SingleAsset variation → asset → prefab name."""
    _write(
        tmp_path / "improvement.xml",
        _wrap(
            """
            <Entry>
                <zType>IMPROVEMENT_LIBRARY_1</zType>
                <zIconName>IMPROVEMENT_LIBRARY</zIconName>
                <AssetVariation>ASSET_VARIATION_IMPROVEMENT_LIBRARY_1</AssetVariation>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VARIATION_IMPROVEMENT_LIBRARY_1</zType>
                <SingleAsset>ASSET_IMPROVEMENT_LIBRARY_1</SingleAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "asset.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_IMPROVEMENT_LIBRARY_1</zType>
                <zAsset>Prefabs/Improvements/Library</zAsset>
            </Entry>
            """
        ),
    )
    result = load_improvement_assets(tmp_path)
    assert result == [
        ImprovementAsset(
            z_icon_name="IMPROVEMENT_LIBRARY",
            prefab_name="Library",
            z_type="IMPROVEMENT_LIBRARY_1",
            asset_z_type="ASSET_IMPROVEMENT_LIBRARY_1",
            weight=1,
        )
    ]


def test_z_icon_name_falls_back_to_z_type(tmp_path: Path) -> None:
    """When <zIconName> is missing, use <zType> as the canonical name."""
    _write(
        tmp_path / "improvement.xml",
        _wrap(
            """
            <Entry>
                <zType>IMPROVEMENT_FARM</zType>
                <AssetVariation>VAR_FARM</AssetVariation>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>VAR_FARM</zType>
                <SingleAsset>ASSET_FARM</SingleAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "asset.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_FARM</zType>
                <zAsset>Prefabs/Improvements/Farm</zAsset>
            </Entry>
            """
        ),
    )
    result = load_improvement_assets(tmp_path)
    assert len(result) == 1
    assert result[0].z_icon_name == "IMPROVEMENT_FARM"
    assert result[0].z_type == "IMPROVEMENT_FARM"


def test_dedupe_by_z_icon_name(tmp_path: Path) -> None:
    """Multiple zTypes sharing a zIconName (upgrade tiers): first one wins.

    This mirrors COURTHOUSE in real game data — IMPROVEMENT_COURTHOUSE_1
    has zIconName=IMPROVEMENT_COURTHOUSE; we render the basic-tier version
    once, not three times.
    """
    _write(
        tmp_path / "improvement.xml",
        _wrap(
            """
            <Entry>
                <zType>IMPROVEMENT_LIBRARY_1</zType>
                <zIconName>IMPROVEMENT_LIBRARY</zIconName>
                <AssetVariation>VAR_1</AssetVariation>
            </Entry>
            <Entry>
                <zType>IMPROVEMENT_LIBRARY_UPGRADE</zType>
                <zIconName>IMPROVEMENT_LIBRARY</zIconName>
                <AssetVariation>VAR_2</AssetVariation>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>VAR_1</zType>
                <SingleAsset>ASSET_BASIC</SingleAsset>
            </Entry>
            <Entry>
                <zType>VAR_2</zType>
                <SingleAsset>ASSET_UPGRADED</SingleAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "asset.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_BASIC</zType>
                <zAsset>Prefabs/Improvements/Library</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_UPGRADED</zType>
                <zAsset>Prefabs/Improvements/Library_upgraded</zAsset>
            </Entry>
            """
        ),
    )
    result = load_improvement_assets(tmp_path)
    assert len(result) == 1
    assert result[0].prefab_name == "Library"  # first entry wins
    assert result[0].z_type == "IMPROVEMENT_LIBRARY_1"


def test_dlc_files_merge_with_base(tmp_path: Path) -> None:
    """Entries split across base + DLC files are all visible to the resolver."""
    _write(
        tmp_path / "improvement.xml",
        _wrap(
            """
            <Entry>
                <zType>IMPROVEMENT_LIBRARY_1</zType>
                <zIconName>IMPROVEMENT_LIBRARY</zIconName>
                <AssetVariation>ASSET_VARIATION_IMPROVEMENT_LIBRARY_1</AssetVariation>
            </Entry>
            <Entry>
                <zType>IMPROVEMENT_ESTATE</zType>
                <AssetVariation>ASSET_VARIATION_IMPROVEMENT_ESTATE</AssetVariation>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VARIATION_IMPROVEMENT_LIBRARY_1</zType>
                <SingleAsset>ASSET_IMPROVEMENT_LIBRARY_1</SingleAsset>
            </Entry>
            """
        ),
    )
    # Estate variation lives in BTT DLC
    _write(
        tmp_path / "assetVariation-btt.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VARIATION_IMPROVEMENT_ESTATE</zType>
                <SingleAsset>ASSET_IMPROVEMENT_ESTATE</SingleAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "asset.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_IMPROVEMENT_LIBRARY_1</zType>
                <zAsset>Prefabs/Improvements/Library</zAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "asset-btt.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_IMPROVEMENT_ESTATE</zType>
                <zAsset>Prefabs/Improvements/Estate</zAsset>
            </Entry>
            """
        ),
    )
    result = load_improvement_assets(tmp_path)
    by_icon = {a.z_icon_name: a.prefab_name for a in result}
    assert by_icon == {
        "IMPROVEMENT_LIBRARY": "Library",
        "IMPROVEMENT_ESTATE": "Estate",
    }


def test_random_assets_picks_highest_weight(tmp_path: Path) -> None:
    """When a variation uses aiRandomAssets, pick the highest-weighted candidate."""
    _write(
        tmp_path / "improvement.xml",
        _wrap(
            """
            <Entry>
                <zType>IMPROVEMENT_FARM</zType>
                <AssetVariation>ASSET_VARIATION_IMPROVEMENT_FARM</AssetVariation>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VARIATION_IMPROVEMENT_FARM</zType>
                <aiRandomAssets>
                    <Pair><zIndex>ASSET_FARM_LOW</zIndex><iValue>1</iValue></Pair>
                    <Pair><zIndex>ASSET_FARM_HIGH</zIndex><iValue>50</iValue></Pair>
                    <Pair><zIndex>ASSET_FARM_MID</zIndex><iValue>10</iValue></Pair>
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
                <zType>ASSET_FARM_LOW</zType>
                <zAsset>Prefabs/Improvements/Farm_low</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_FARM_HIGH</zType>
                <zAsset>Prefabs/Improvements/Farm_high</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_FARM_MID</zType>
                <zAsset>Prefabs/Improvements/Farm_mid</zAsset>
            </Entry>
            """
        ),
    )
    result = load_improvement_assets(tmp_path)
    assert len(result) == 1
    assert result[0].prefab_name == "Farm_high"
    assert result[0].weight == 50


def test_random_assets_ties_broken_by_document_order(tmp_path: Path) -> None:
    """Equal weights → the first one in document order wins."""
    _write(
        tmp_path / "improvement.xml",
        _wrap(
            """
            <Entry>
                <zType>IMPROVEMENT_X</zType>
                <AssetVariation>VAR_X</AssetVariation>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>VAR_X</zType>
                <aiRandomAssets>
                    <Pair><zIndex>ASSET_FIRST</zIndex><iValue>5</iValue></Pair>
                    <Pair><zIndex>ASSET_SECOND</zIndex><iValue>5</iValue></Pair>
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
                <zType>ASSET_FIRST</zType>
                <zAsset>Prefabs/Improvements/A</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_SECOND</zType>
                <zAsset>Prefabs/Improvements/B</zAsset>
            </Entry>
            """
        ),
    )
    result = load_improvement_assets(tmp_path)
    assert len(result) == 1
    assert result[0].prefab_name == "A"


def test_broken_chain_skipped(tmp_path: Path) -> None:
    """Improvements with missing variation/asset entries are silently skipped."""
    _write(
        tmp_path / "improvement.xml",
        _wrap(
            """
            <Entry>
                <zType>IMPROVEMENT_GOOD</zType>
                <AssetVariation>VAR_GOOD</AssetVariation>
            </Entry>
            <Entry>
                <zType>IMPROVEMENT_NO_VARIATION</zType>
                <AssetVariation>VAR_MISSING</AssetVariation>
            </Entry>
            <Entry>
                <zType>IMPROVEMENT_NO_ASSET</zType>
                <AssetVariation>VAR_NO_ASSET</AssetVariation>
            </Entry>
            <Entry>
                <zType>IMPROVEMENT_NO_FIELD</zType>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>VAR_GOOD</zType>
                <SingleAsset>ASSET_GOOD</SingleAsset>
            </Entry>
            <Entry>
                <zType>VAR_NO_ASSET</zType>
                <SingleAsset>ASSET_MISSING</SingleAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "asset.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_GOOD</zType>
                <zAsset>Prefabs/Improvements/Good</zAsset>
            </Entry>
            """
        ),
    )
    result = load_improvement_assets(tmp_path)
    assert [a.z_icon_name for a in result] == ["IMPROVEMENT_GOOD"]


def test_prefab_name_extracted_from_nested_path(tmp_path: Path) -> None:
    """zAsset path can be deeply nested (e.g., DLC city prefabs); we want
    the last path component as the GameObject name."""
    _write(
        tmp_path / "improvement.xml",
        _wrap(
            """
            <Entry>
                <zType>IMPROVEMENT_MAURYA_CAPITAL</zType>
                <AssetVariation>VAR_MAURYA</AssetVariation>
            </Entry>
            <Entry>
                <zType>IMPROVEMENT_ISHTAR</zType>
                <AssetVariation>VAR_ISHTAR</AssetVariation>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>VAR_MAURYA</zType>
                <SingleAsset>ASSET_MAURYA</SingleAsset>
            </Entry>
            <Entry>
                <zType>VAR_ISHTAR</zType>
                <SingleAsset>ASSET_ISHTAR</SingleAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "asset.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_MAURYA</zType>
                <zAsset>Prefabs/Cities/Maurya/Maurya_Capital</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_ISHTAR</zType>
                <zAsset>Prefabs/Features/Ishtar_Gate</zAsset>
            </Entry>
            """
        ),
    )
    result = load_improvement_assets(tmp_path)
    by_icon = {a.z_icon_name: a.prefab_name for a in result}
    assert by_icon == {
        "IMPROVEMENT_MAURYA_CAPITAL": "Maurya_Capital",
        "IMPROVEMENT_ISHTAR": "Ishtar_Gate",
    }


def test_missing_xml_dir_returns_empty(tmp_path: Path) -> None:
    """Pointing at a non-existent directory returns [] without crashing."""
    result = load_improvement_assets(tmp_path / "does_not_exist")
    assert result == []


# --- load_capital_assets -----------------------------------------------------


def test_capitals_discovered_via_variation_pattern(tmp_path: Path) -> None:
    """Capitals are discovered by scanning ASSET_VARIATION_CITY_*_CAPITAL
    entries in assetVariation.xml — they have no improvement.xml row."""
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VARIATION_CITY_GREECE_CAPITAL</zType>
                <SingleAsset>ASSET_CITY_GREECE_CAPITAL</SingleAsset>
            </Entry>
            <Entry>
                <zType>ASSET_VARIATION_CITY_GREECE_URBAN</zType>
                <SingleAsset>ASSET_CITY_GREECE_URBAN</SingleAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "assetVariation-eoti.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VARIATION_CITY_MAURYA_CAPITAL</zType>
                <SingleAsset>ASSET_CITY_MAURYA_CAPITAL</SingleAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "asset.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_CITY_GREECE_CAPITAL</zType>
                <zAsset>Prefabs/Cities/Greece/Greece_Capital</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_CITY_GREECE_URBAN</zType>
                <zAsset>Prefabs/Cities/Greece/Greece_Urban</zAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "asset-eoti.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_CITY_MAURYA_CAPITAL</zType>
                <zAsset>Prefabs/Cities/Maurya/Maurya_Capital</zAsset>
            </Entry>
            """
        ),
    )
    result = load_capital_assets(tmp_path)
    by_canonical = {a.z_icon_name: a.prefab_name for a in result}
    # Capitals only — no urban tiles, even though _URBAN variation exists.
    assert by_canonical == {
        "GREECE_CAPITAL": "Greece_Capital",
        "MAURYA_CAPITAL": "Maurya_Capital",
    }


def test_capitals_skip_when_asset_missing(tmp_path: Path) -> None:
    """Variation entry exists but downstream Asset is missing → skipped."""
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VARIATION_CITY_NOWHERE_CAPITAL</zType>
                <SingleAsset>ASSET_CITY_NOWHERE_CAPITAL</SingleAsset>
            </Entry>
            """
        ),
    )
    _write(tmp_path / "asset.xml", _wrap(""))
    result = load_capital_assets(tmp_path)
    assert result == []


def test_capitals_missing_xml_returns_empty(tmp_path: Path) -> None:
    result = load_capital_assets(tmp_path / "does_not_exist")
    assert result == []


def test_urban_tiles_discovered_from_asset_xml(tmp_path: Path) -> None:
    """Urban tiles are direct asset.xml entries (no AssetVariation wrapper).

    Filters out the generic ASSET_URBAN (Primitive) and the
    ASSET_TERRAIN_URBAN_FLAT terrain tile, both of which match the
    ASSET_*_URBAN suffix but aren't per-nation visualizations.
    """
    _write(
        tmp_path / "asset.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_GREECE_URBAN</zType>
                <zAsset>Prefabs/Cities/Greece/Greece_Urban</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_EGYPT_URBAN</zType>
                <zAsset>Prefabs/Cities/Egypt/Egypt_Urban</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_URBAN</zType>
                <zAsset>Prefabs/Cities/Primitive/PrimitiveUrban</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_TERRAIN_URBAN_FLAT</zType>
                <zAsset>Prefabs/Terrain/TileUrban</zAsset>
            </Entry>
            """
        ),
    )
    result = load_urban_assets(tmp_path)
    by_canonical = {a.z_icon_name: a.prefab_name for a in result}
    assert by_canonical == {
        "GREECE_URBAN": "Greece_Urban",
        "EGYPT_URBAN": "Egypt_Urban",
    }


def test_urban_tiles_dlc_files_merged(tmp_path: Path) -> None:
    _write(
        tmp_path / "asset.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_GREECE_URBAN</zType>
                <zAsset>Prefabs/Cities/Greece/Greece_Urban</zAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "asset-eoti.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_HITTITE_URBAN</zType>
                <zAsset>Prefabs/Cities/Hittite/Hittite_Urban</zAsset>
            </Entry>
            """
        ),
    )
    result = load_urban_assets(tmp_path)
    canonical = {a.z_icon_name for a in result}
    assert canonical == {"GREECE_URBAN", "HITTITE_URBAN"}


def test_urban_tiles_missing_xml_returns_empty(tmp_path: Path) -> None:
    result = load_urban_assets(tmp_path / "does_not_exist")
    assert result == []


def test_urban_tiles_skipped_when_zasset_missing(tmp_path: Path) -> None:
    _write(
        tmp_path / "asset.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_GREECE_URBAN</zType>
            </Entry>
            """
        ),
    )
    assert load_urban_assets(tmp_path) == []


def test_urban_tile_returns_full_asset_record(tmp_path: Path) -> None:
    _write(
        tmp_path / "asset.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_PERSIA_URBAN</zType>
                <zAsset>Prefabs/Cities/Persia/Persia_Urban</zAsset>
            </Entry>
            """
        ),
    )
    [asset] = load_urban_assets(tmp_path)
    assert asset == ImprovementAsset(
        z_icon_name="PERSIA_URBAN",
        prefab_name="Persia_Urban",
        z_type="ASSET_PERSIA_URBAN",
        asset_z_type="ASSET_PERSIA_URBAN",
        weight=1,
    )


# --- load_resource_assets ----------------------------------------------------


def test_resource_single_asset_chain_resolves(tmp_path: Path) -> None:
    _write(
        tmp_path / "resource.xml",
        _wrap(
            """
            <Entry>
                <zType>RESOURCE_CATTLE</zType>
                <zIconName>RESOURCE_CATTLE</zIconName>
                <AssetVariation>ASSET_VARIATION_RESOURCE_CATTLE</AssetVariation>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VARIATION_RESOURCE_CATTLE</zType>
                <SingleAsset>ASSET_RESOURCE_CATTLE</SingleAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "asset.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_RESOURCE_CATTLE</zType>
                <zAsset>Prefabs/Resource/Cattle</zAsset>
            </Entry>
            """
        ),
    )
    [asset] = load_resource_assets(tmp_path)
    assert asset == ImprovementAsset(
        z_icon_name="RESOURCE_CATTLE",
        prefab_name="Cattle",
        z_type="RESOURCE_CATTLE",
        asset_z_type="ASSET_RESOURCE_CATTLE",
        weight=1,
    )


def test_resource_z_icon_name_aliases_to_shared_visual(tmp_path: Path) -> None:
    """RESOURCE_ORE has zIconName=RESOURCE_IRON — output filename uses
    RESOURCE_IRON (canonical icon), but the chain follows
    ASSET_VARIATION_RESOURCE_ORE."""
    _write(
        tmp_path / "resource.xml",
        _wrap(
            """
            <Entry>
                <zType>RESOURCE_ORE</zType>
                <zIconName>RESOURCE_IRON</zIconName>
                <AssetVariation>ASSET_VARIATION_RESOURCE_ORE</AssetVariation>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VARIATION_RESOURCE_ORE</zType>
                <SingleAsset>ASSET_RESOURCE_IRON</SingleAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "asset.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_RESOURCE_IRON</zType>
                <zAsset>Prefabs/Resource/Iron</zAsset>
            </Entry>
            """
        ),
    )
    [asset] = load_resource_assets(tmp_path)
    assert asset.z_icon_name == "RESOURCE_IRON"
    assert asset.z_type == "RESOURCE_ORE"
    assert asset.prefab_name == "Iron"


def test_resource_random_assets_picks_highest_weight(tmp_path: Path) -> None:
    """RESOURCE_HORSE uses aiRandomAssets (Horse_01 weight 6, Horse_02 weight 4).
    The loader picks the highest-weighted candidate, mirroring improvements."""
    _write(
        tmp_path / "resource.xml",
        _wrap(
            """
            <Entry>
                <zType>RESOURCE_HORSE</zType>
                <zIconName>RESOURCE_HORSE</zIconName>
                <AssetVariation>ASSET_VARIATION_RESOURCE_HORSE</AssetVariation>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VARIATION_RESOURCE_HORSE</zType>
                <aiRandomAssets>
                    <Pair>
                        <zIndex>ASSET_RESOURCE_HORSE_01</zIndex>
                        <iValue>6</iValue>
                    </Pair>
                    <Pair>
                        <zIndex>ASSET_RESOURCE_HORSE_02</zIndex>
                        <iValue>4</iValue>
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
                <zType>ASSET_RESOURCE_HORSE_01</zType>
                <zAsset>Prefabs/Resource/Horse_Variation/Horse_01</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_RESOURCE_HORSE_02</zType>
                <zAsset>Prefabs/Resource/Horse_Variation/Horse_02</zAsset>
            </Entry>
            """
        ),
    )
    [asset] = load_resource_assets(tmp_path)
    assert asset.prefab_name == "Horse_01"
    assert asset.weight == 6


def test_resource_dlc_files_merge(tmp_path: Path) -> None:
    """DLC additions (resource-eoti.xml etc.) merge with the base file."""
    _write(
        tmp_path / "resource.xml",
        _wrap(
            """
            <Entry>
                <zType>RESOURCE_CATTLE</zType>
                <AssetVariation>ASSET_VARIATION_RESOURCE_CATTLE</AssetVariation>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "resource-eoti.xml",
        _wrap(
            """
            <Entry>
                <zType>RESOURCE_JADE</zType>
                <AssetVariation>ASSET_VARIATION_RESOURCE_JADE</AssetVariation>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VARIATION_RESOURCE_CATTLE</zType>
                <SingleAsset>ASSET_RESOURCE_CATTLE</SingleAsset>
            </Entry>
            <Entry>
                <zType>ASSET_VARIATION_RESOURCE_JADE</zType>
                <SingleAsset>ASSET_RESOURCE_JADE</SingleAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "asset.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_RESOURCE_CATTLE</zType>
                <zAsset>Prefabs/Resource/Cattle</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_RESOURCE_JADE</zType>
                <zAsset>Prefabs/Resource/Jade</zAsset>
            </Entry>
            """
        ),
    )
    result = load_resource_assets(tmp_path)
    assert {a.z_type for a in result} == {"RESOURCE_CATTLE", "RESOURCE_JADE"}


def test_resource_dedupe_by_z_icon_name(tmp_path: Path) -> None:
    """Multiple zTypes sharing one zIconName collapse to a single record."""
    _write(
        tmp_path / "resource.xml",
        _wrap(
            """
            <Entry>
                <zType>RESOURCE_ORE</zType>
                <zIconName>RESOURCE_IRON</zIconName>
                <AssetVariation>ASSET_VARIATION_RESOURCE_ORE</AssetVariation>
            </Entry>
            <Entry>
                <zType>RESOURCE_IRON_DUPLICATE</zType>
                <zIconName>RESOURCE_IRON</zIconName>
                <AssetVariation>ASSET_VARIATION_RESOURCE_DUP</AssetVariation>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VARIATION_RESOURCE_ORE</zType>
                <SingleAsset>ASSET_RESOURCE_IRON</SingleAsset>
            </Entry>
            <Entry>
                <zType>ASSET_VARIATION_RESOURCE_DUP</zType>
                <SingleAsset>ASSET_RESOURCE_IRON_DUP</SingleAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "asset.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_RESOURCE_IRON</zType>
                <zAsset>Prefabs/Resource/Iron</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_RESOURCE_IRON_DUP</zType>
                <zAsset>Prefabs/Resource/IronDup</zAsset>
            </Entry>
            """
        ),
    )
    [asset] = load_resource_assets(tmp_path)
    assert asset.z_type == "RESOURCE_ORE"
    assert asset.prefab_name == "Iron"


def test_resource_missing_xml_returns_empty(tmp_path: Path) -> None:
    assert load_resource_assets(tmp_path / "does_not_exist") == []


def test_resource_broken_chain_skipped(tmp_path: Path) -> None:
    """Resources with no AssetVariation, missing variation entry, or
    missing asset entry are skipped silently."""
    _write(
        tmp_path / "resource.xml",
        _wrap(
            """
            <Entry>
                <zType>RESOURCE_NOAV</zType>
            </Entry>
            <Entry>
                <zType>RESOURCE_DANGLING_AV</zType>
                <AssetVariation>ASSET_VARIATION_MISSING</AssetVariation>
            </Entry>
            <Entry>
                <zType>RESOURCE_DANGLING_ASSET</zType>
                <AssetVariation>ASSET_VARIATION_RESOURCE_X</AssetVariation>
            </Entry>
            <Entry>
                <zType>RESOURCE_OK</zType>
                <AssetVariation>ASSET_VARIATION_RESOURCE_OK</AssetVariation>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VARIATION_RESOURCE_X</zType>
                <SingleAsset>ASSET_MISSING</SingleAsset>
            </Entry>
            <Entry>
                <zType>ASSET_VARIATION_RESOURCE_OK</zType>
                <SingleAsset>ASSET_RESOURCE_OK</SingleAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "asset.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_RESOURCE_OK</zType>
                <zAsset>Prefabs/Resource/Ok</zAsset>
            </Entry>
            """
        ),
    )
    [asset] = load_resource_assets(tmp_path)
    assert asset.z_type == "RESOURCE_OK"


# ============================================================
# load_urban_renderable_improvements
# ============================================================


def _write_urban_chain_basics(tmp_path: Path) -> None:
    """Set up terrainTarget + assetVariation + asset for the canonical
    Library/Pyramids/etc. test improvements used across the urban-renderable
    cases below."""
    # Minimal terrainTarget.xml: HABITABLE includes urban (Library, Theater,
    # etc. resolve through this); DRY does not (Pyramids).
    _write(
        tmp_path / "terrainTarget.xml",
        _wrap(
            """
            <Entry>
                <zType>TERRAIN_TARGET_HABITABLE</zType>
                <Terrains>
                    <zValue>TERRAIN_URBAN</zValue>
                    <zValue>TERRAIN_TEMPERATE</zValue>
                </Terrains>
            </Entry>
            <Entry>
                <zType>TERRAIN_TARGET_DRY</zType>
                <Terrains>
                    <zValue>TERRAIN_ARID</zValue>
                    <zValue>TERRAIN_SAND</zValue>
                </Terrains>
            </Entry>
            <Entry>
                <zType>TERRAIN_TARGET_HILL</zType>
                <Heights>
                    <zValue>HEIGHT_HILL</zValue>
                </Heights>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VARIATION_IMPROVEMENT_LIBRARY_1</zType>
                <SingleAsset>ASSET_IMPROVEMENT_LIBRARY_1</SingleAsset>
            </Entry>
            <Entry>
                <zType>ASSET_VARIATION_IMPROVEMENT_PYRAMIDS</zType>
                <SingleAsset>ASSET_IMPROVEMENT_PYRAMIDS</SingleAsset>
            </Entry>
            <Entry>
                <zType>ASSET_VARIATION_IMPROVEMENT_SHRINE_ATHENA</zType>
                <SingleAsset>ASSET_IMPROVEMENT_SHRINE_ATHENA</SingleAsset>
            </Entry>
            <Entry>
                <zType>ASSET_VARIATION_IMPROVEMENT_SHRINE_SERAPIS</zType>
                <SingleAsset>ASSET_IMPROVEMENT_SHRINE_SERAPIS</SingleAsset>
            </Entry>
            <Entry>
                <zType>ASSET_VARIATION_IMPROVEMENT_SHRINE_OF_VICTORY</zType>
                <SingleAsset>ASSET_IMPROVEMENT_SHRINE_OF_VICTORY</SingleAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "asset.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_IMPROVEMENT_LIBRARY_1</zType>
                <zAsset>Prefabs/Improvements/Library</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_IMPROVEMENT_PYRAMIDS</zType>
                <zAsset>Prefabs/Improvements/Pyramids</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_IMPROVEMENT_SHRINE_ATHENA</zType>
                <zAsset>Prefabs/Improvements/Shrine_Wisdom</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_IMPROVEMENT_SHRINE_SERAPIS</zType>
                <zAsset>Prefabs/Improvements/Shrine_Sun</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_IMPROVEMENT_SHRINE_OF_VICTORY</zType>
                <zAsset>Prefabs/Improvements/Shrine_Fire</zAsset>
            </Entry>
            """
        ),
    )


def test_urban_renderable_includes_universal_improvement(tmp_path: Path) -> None:
    """A bUrban=1 improvement with no nation/dynasty/terrain lock and no
    scenario gate should be returned with nation_prereq=None."""
    _write_urban_chain_basics(tmp_path)
    _write(
        tmp_path / "improvement.xml",
        _wrap(
            """
            <Entry>
                <zType>IMPROVEMENT_LIBRARY_1</zType>
                <zIconName>IMPROVEMENT_LIBRARY</zIconName>
                <bUrban>1</bUrban>
                <AssetVariation>ASSET_VARIATION_IMPROVEMENT_LIBRARY_1</AssetVariation>
            </Entry>
            """
        ),
    )
    [imp] = load_urban_renderable_improvements(tmp_path)
    assert imp == UrbanRenderableImprovement(
        z_icon_name="IMPROVEMENT_LIBRARY",
        z_type="IMPROVEMENT_LIBRARY_1",
        prefab_name="Library",
        nation_prereq=None,
    )


def test_urban_renderable_excludes_terrain_locked_wonder(tmp_path: Path) -> None:
    """Pyramids has bUrban=1 but a `<TerrainValid>` block restricting it to
    TERRAIN_TARGET_DRY only → can never land on TERRAIN_URBAN, must be
    excluded from the urban-composite filter. The presence of the
    `<TerrainValid>` element alone is sufficient (verified against XML:
    no urban-renderable improvement has a `<TerrainValid>` element)."""
    _write_urban_chain_basics(tmp_path)
    _write(
        tmp_path / "improvement.xml",
        _wrap(
            """
            <Entry>
                <zType>IMPROVEMENT_PYRAMIDS</zType>
                <bUrban>1</bUrban>
                <bWonder>1</bWonder>
                <TerrainValid>
                    <zValue>TERRAIN_TARGET_DRY</zValue>
                </TerrainValid>
                <AssetVariation>ASSET_VARIATION_IMPROVEMENT_PYRAMIDS</AssetVariation>
            </Entry>
            """
        ),
    )
    assert load_urban_renderable_improvements(tmp_path) == []


def test_urban_renderable_includes_terrain_valid_with_urban_target(tmp_path: Path) -> None:
    """Library has TerrainValid=HABITABLE → resolves to TERRAIN_URBAN
    (among others) → urban-renderable. Verifies the terrainTarget.xml
    resolution path."""
    _write_urban_chain_basics(tmp_path)
    _write(
        tmp_path / "improvement.xml",
        _wrap(
            """
            <Entry>
                <zType>IMPROVEMENT_LIBRARY_1</zType>
                <zIconName>IMPROVEMENT_LIBRARY</zIconName>
                <bUrban>1</bUrban>
                <TerrainValid>
                    <zValue>TERRAIN_TARGET_HABITABLE</zValue>
                </TerrainValid>
                <AssetVariation>ASSET_VARIATION_IMPROVEMENT_LIBRARY_1</AssetVariation>
            </Entry>
            """
        ),
    )
    [imp] = load_urban_renderable_improvements(tmp_path)
    assert imp.z_icon_name == "IMPROVEMENT_LIBRARY"


def test_urban_renderable_captures_nation_prereq(tmp_path: Path) -> None:
    """Nation-tied shrines carry their `<NationPrereq>` so the extractor
    can render only on that nation's urban tile."""
    _write_urban_chain_basics(tmp_path)
    _write(
        tmp_path / "improvement.xml",
        _wrap(
            """
            <Entry>
                <zType>IMPROVEMENT_SHRINE_ATHENA</zType>
                <bUrban>1</bUrban>
                <NationPrereq>NATION_GREECE</NationPrereq>
                <AssetVariation>ASSET_VARIATION_IMPROVEMENT_SHRINE_ATHENA</AssetVariation>
            </Entry>
            """
        ),
    )
    [imp] = load_urban_renderable_improvements(tmp_path)
    assert imp.nation_prereq == "NATION_GREECE"


def test_urban_renderable_resolves_dynasty_to_nation(tmp_path: Path) -> None:
    """Dynasty-locked improvements (Serapis under DYNASTY_PTOLEMY) get
    mapped to a nation via the `_DYNASTY_TO_NATION` table."""
    _write_urban_chain_basics(tmp_path)
    _write(
        tmp_path / "improvement.xml",
        _wrap(
            """
            <Entry>
                <zType>IMPROVEMENT_SHRINE_SERAPIS</zType>
                <bUrban>1</bUrban>
                <DynastyPrereq>DYNASTY_PTOLEMY</DynastyPrereq>
                <AssetVariation>ASSET_VARIATION_IMPROVEMENT_SHRINE_SERAPIS</AssetVariation>
            </Entry>
            """
        ),
    )
    [imp] = load_urban_renderable_improvements(tmp_path)
    assert imp.nation_prereq == "NATION_EGYPT"


def test_urban_renderable_excludes_scenario_eventpack(tmp_path: Path) -> None:
    """Scenario-only event content (`GameContentRequired=EVENTPACK_*`) is
    excluded — covers the 3 cult shrines in `improvement-event-sap.xml`."""
    _write_urban_chain_basics(tmp_path)
    _write(
        tmp_path / "improvement-event-sap.xml",
        _wrap(
            """
            <Entry>
                <zType>IMPROVEMENT_SHRINE_OF_VICTORY</zType>
                <bUrban>1</bUrban>
                <GameContentRequired>EVENTPACK_RELIGION</GameContentRequired>
                <AssetVariation>ASSET_VARIATION_IMPROVEMENT_SHRINE_OF_VICTORY</AssetVariation>
            </Entry>
            """
        ),
    )
    assert load_urban_renderable_improvements(tmp_path) == []


def test_urban_renderable_excludes_non_urban_improvements(tmp_path: Path) -> None:
    """Improvements without `<bUrban>1</bUrban>` (Farm, Mine, etc.) are
    excluded outright."""
    _write_urban_chain_basics(tmp_path)
    _write(
        tmp_path / "improvement.xml",
        _wrap(
            """
            <Entry>
                <zType>IMPROVEMENT_FARM</zType>
                <AssetVariation>ASSET_VARIATION_IMPROVEMENT_LIBRARY_1</AssetVariation>
            </Entry>
            """
        ),
    )
    assert load_urban_renderable_improvements(tmp_path) == []


def test_urban_renderable_keeps_shared_icon_per_nation(tmp_path: Path) -> None:
    """Real-game case: Greek Zeus shrine and Babylonian Marduk shrine both
    use IMPROVEMENT_SHRINE_KINGSHIP as their zIconName (one of 11 shared
    art assets). They're DIFFERENT outputs because they appear on
    different nations' urban tiles. Dedupe key is (icon, nation)."""
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VARIATION_IMPROVEMENT_SHRINE_ZEUS</zType>
                <SingleAsset>ASSET_IMPROVEMENT_SHRINE_KINGSHIP</SingleAsset>
            </Entry>
            <Entry>
                <zType>ASSET_VARIATION_IMPROVEMENT_SHRINE_MARDUK</zType>
                <SingleAsset>ASSET_IMPROVEMENT_SHRINE_KINGSHIP</SingleAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "asset.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_IMPROVEMENT_SHRINE_KINGSHIP</zType>
                <zAsset>Prefabs/Improvements/KingshipShrine</zAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "improvement.xml",
        _wrap(
            """
            <Entry>
                <zType>IMPROVEMENT_SHRINE_ZEUS</zType>
                <zIconName>IMPROVEMENT_SHRINE_KINGSHIP</zIconName>
                <bUrban>1</bUrban>
                <NationPrereq>NATION_GREECE</NationPrereq>
                <AssetVariation>ASSET_VARIATION_IMPROVEMENT_SHRINE_ZEUS</AssetVariation>
            </Entry>
            <Entry>
                <zType>IMPROVEMENT_SHRINE_MARDUK</zType>
                <zIconName>IMPROVEMENT_SHRINE_KINGSHIP</zIconName>
                <bUrban>1</bUrban>
                <NationPrereq>NATION_BABYLONIA</NationPrereq>
                <AssetVariation>ASSET_VARIATION_IMPROVEMENT_SHRINE_MARDUK</AssetVariation>
            </Entry>
            """
        ),
    )
    result = load_urban_renderable_improvements(tmp_path)
    by_nation = {r.nation_prereq: r.z_type for r in result}
    assert by_nation == {
        "NATION_GREECE": "IMPROVEMENT_SHRINE_ZEUS",
        "NATION_BABYLONIA": "IMPROVEMENT_SHRINE_MARDUK",
    }


def test_urban_renderable_dedupes_on_z_icon_name(tmp_path: Path) -> None:
    """Tier collapse: Library_1 and Library_2 sharing zIconName=
    IMPROVEMENT_LIBRARY should produce one entry (Library_1, first seen)."""
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VARIATION_IMPROVEMENT_LIBRARY_1</zType>
                <SingleAsset>ASSET_IMPROVEMENT_LIBRARY_1</SingleAsset>
            </Entry>
            <Entry>
                <zType>ASSET_VARIATION_IMPROVEMENT_LIBRARY_2</zType>
                <SingleAsset>ASSET_IMPROVEMENT_LIBRARY_2</SingleAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "asset.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_IMPROVEMENT_LIBRARY_1</zType>
                <zAsset>Prefabs/Improvements/Library</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_IMPROVEMENT_LIBRARY_2</zType>
                <zAsset>Prefabs/Improvements/Library_Tier2</zAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "improvement.xml",
        _wrap(
            """
            <Entry>
                <zType>IMPROVEMENT_LIBRARY_1</zType>
                <zIconName>IMPROVEMENT_LIBRARY</zIconName>
                <bUrban>1</bUrban>
                <AssetVariation>ASSET_VARIATION_IMPROVEMENT_LIBRARY_1</AssetVariation>
            </Entry>
            <Entry>
                <zType>IMPROVEMENT_LIBRARY_2</zType>
                <zIconName>IMPROVEMENT_LIBRARY</zIconName>
                <bUrban>1</bUrban>
                <AssetVariation>ASSET_VARIATION_IMPROVEMENT_LIBRARY_2</AssetVariation>
            </Entry>
            """
        ),
    )
    [imp] = load_urban_renderable_improvements(tmp_path)
    assert imp.z_type == "IMPROVEMENT_LIBRARY_1"
    assert imp.prefab_name == "Library"


# ============================================================
# Vegetation chain
# ============================================================
#
# `load_vegetation_assets` scans every `ASSET_VARIATION_VEGETATION_*`
# entry — independent of `vegetation.xml` — and parses
# (terrain, height) from the variation name suffix. Tests cover the
# parser, the multi-candidate `_NN` expansion, prefab dedup within a
# single variation, and the full base / hill / arid / charred /
# hurricane suffix matrix.


def test_vegetation_single_asset_resolves(tmp_path: Path) -> None:
    """One SingleAsset variation produces one VegetationAsset with default
    TEMPERATE / FLAT and no `_NN` suffix on output_name."""
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VARIATION_VEGETATION_TREES_CUT</zType>
                <SingleAsset>ASSET_VEGETATION_TREES_CUT</SingleAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "asset.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VEGETATION_TREES_CUT</zType>
                <zAsset>Prefabs/Features/Trees/ForestCut</zAsset>
            </Entry>
            """
        ),
    )
    [veg] = load_vegetation_assets(tmp_path)
    assert veg == VegetationAsset(
        output_name="TREES_CUT",
        prefab_name="ForestCut",
        variation_z_type="ASSET_VARIATION_VEGETATION_TREES_CUT",
        asset_z_type="ASSET_VEGETATION_TREES_CUT",
        terrain_z_type="TERRAIN_TEMPERATE",
        height_z_type="HEIGHT_FLAT",
    )


def test_vegetation_random_assets_expand_with_padded_suffix(tmp_path: Path) -> None:
    """`aiRandomAssets` with N distinct prefabs emits N VegetationAssets
    with zero-padded `_NN` suffixes matching candidate order."""
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VARIATION_VEGETATION_JUNGLE</zType>
                <aiRandomAssets>
                    <Pair><zIndex>ASSET_VEGETATION_JUNGLE_1</zIndex><iValue>1</iValue></Pair>
                    <Pair><zIndex>ASSET_VEGETATION_JUNGLE_2</zIndex><iValue>1</iValue></Pair>
                    <Pair><zIndex>ASSET_VEGETATION_JUNGLE_3</zIndex><iValue>1</iValue></Pair>
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
                <zType>ASSET_VEGETATION_JUNGLE_1</zType>
                <zAsset>Prefabs/Resource/Jungle_01</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_VEGETATION_JUNGLE_2</zType>
                <zAsset>Prefabs/Resource/Jungle-02</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_VEGETATION_JUNGLE_3</zType>
                <zAsset>Prefabs/Resource/Jungle_03</zAsset>
            </Entry>
            """
        ),
    )
    result = load_vegetation_assets(tmp_path)
    output_names = sorted(v.output_name for v in result)
    assert output_names == ["JUNGLE_01", "JUNGLE_02", "JUNGLE_03"]
    prefabs = sorted(v.prefab_name for v in result)
    assert prefabs == ["Jungle-02", "Jungle_01", "Jungle_03"]


def test_vegetation_random_assets_dedupe_by_prefab(tmp_path: Path) -> None:
    """When several `aiRandomAssets` candidates resolve to the same prefab
    we emit one VegetationAsset per unique prefab — same prefab rendered
    three times would just produce three identical PNGs."""
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VARIATION_VEGETATION_TREES_CHARRED</zType>
                <aiRandomAssets>
                    <Pair><zIndex>ASSET_VEGETATION_TREES_CHARRED</zIndex><iValue>1</iValue></Pair>
                    <Pair><zIndex>ASSET_VEGETATION_TREES_02_CHARRED</zIndex><iValue>1</iValue></Pair>
                    <Pair><zIndex>ASSET_VEGETATION_TREES_03_CHARRED</zIndex><iValue>1</iValue></Pair>
                </aiRandomAssets>
            </Entry>
            """
        ),
    )
    # First two assets resolve to the same _02 prefab (mirrors the
    # actual base-game data) — only the third is distinct.
    _write(
        tmp_path / "asset.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VEGETATION_TREES_CHARRED</zType>
                <zAsset>Prefabs/Vegetation/Temperate_Tree_02_Cluster_Impostors_Charred</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_VEGETATION_TREES_02_CHARRED</zType>
                <zAsset>Prefabs/Vegetation/Temperate_Tree_02_Cluster_Impostors_Charred</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_VEGETATION_TREES_03_CHARRED</zType>
                <zAsset>Prefabs/Vegetation/Temperate_Tree_03_Cluster_Impostors_Charred</zAsset>
            </Entry>
            """
        ),
    )
    result = load_vegetation_assets(tmp_path)
    output_names = sorted(v.output_name for v in result)
    assert output_names == ["TREES_CHARRED_01", "TREES_CHARRED_02"]


def test_vegetation_terrain_and_height_parsed_from_suffix(tmp_path: Path) -> None:
    """ARID and HILL tokens in the variation name set the right
    `terrain_z_type` / `height_z_type` for biome ground lookup."""
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VARIATION_VEGETATION_TREES_HILL</zType>
                <SingleAsset>ASSET_VEGETATION_TREES_HILL</SingleAsset>
            </Entry>
            <Entry>
                <zType>ASSET_VARIATION_VEGETATION_TREES_ARID</zType>
                <SingleAsset>ASSET_VEGETATION_TREES_ARID</SingleAsset>
            </Entry>
            <Entry>
                <zType>ASSET_VARIATION_VEGETATION_TREES_HILL_HURRICANE</zType>
                <SingleAsset>ASSET_VEGETATION_TREES_HILL_HURRICANE</SingleAsset>
            </Entry>
            <Entry>
                <zType>ASSET_VARIATION_VEGETATION_TREES_ARID_CHARRED_MINOR</zType>
                <SingleAsset>ASSET_VEGETATION_TREES_ARID_CHARRED_MINOR</SingleAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "asset.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VEGETATION_TREES_HILL</zType>
                <zAsset>Prefabs/Features/Trees/Temperate_Tree_01_Cluster_Hill_Impostors</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_VEGETATION_TREES_ARID</zType>
                <zAsset>Prefabs/Features/Trees/Arid_Tree_01_Cluster_Impostors</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_VEGETATION_TREES_HILL_HURRICANE</zType>
                <zAsset>Prefabs/Hurricane/Temperate_Tree_01_Cluster_Hill_Impostors Hurricane</zAsset>
            </Entry>
            <Entry>
                <zType>ASSET_VEGETATION_TREES_ARID_CHARRED_MINOR</zType>
                <zAsset>Prefabs/Vegetation/Arid_Tree_01_Charred_Minor</zAsset>
            </Entry>
            """
        ),
    )
    result = load_vegetation_assets(tmp_path)
    by_name = {v.output_name: v for v in result}
    assert by_name["TREES_HILL"].terrain_z_type == "TERRAIN_TEMPERATE"
    assert by_name["TREES_HILL"].height_z_type == "HEIGHT_HILL"
    assert by_name["TREES_ARID"].terrain_z_type == "TERRAIN_ARID"
    assert by_name["TREES_ARID"].height_z_type == "HEIGHT_FLAT"
    assert by_name["TREES_HILL_HURRICANE"].terrain_z_type == "TERRAIN_TEMPERATE"
    assert by_name["TREES_HILL_HURRICANE"].height_z_type == "HEIGHT_HILL"
    assert by_name["TREES_ARID_CHARRED_MINOR"].terrain_z_type == "TERRAIN_ARID"
    assert by_name["TREES_ARID_CHARRED_MINOR"].height_z_type == "HEIGHT_FLAT"


def test_vegetation_hurricane_prefab_with_space_in_name(tmp_path: Path) -> None:
    """Hurricane prefab paths in `asset.xml` carry a literal space
    (`Temperate_Tree_01_Cluster_Impostors Hurricane`); the prefab-name
    extractor (`rsplit('/', 1)`) keeps the space — nothing special, but
    worth pinning so a future cleanup doesn't regress."""
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VARIATION_VEGETATION_TREES_HURRICANE</zType>
                <SingleAsset>ASSET_VEGETATION_TREES_HURRICANE</SingleAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "asset.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VEGETATION_TREES_HURRICANE</zType>
                <zAsset>Prefabs/Hurricane/Temperate_Tree_01_Cluster_Impostors Hurricane</zAsset>
            </Entry>
            """
        ),
    )
    [veg] = load_vegetation_assets(tmp_path)
    assert veg.prefab_name == "Temperate_Tree_01_Cluster_Impostors Hurricane"


def test_vegetation_dlc_files_merge(tmp_path: Path) -> None:
    """DLC additions in `assetVariation-eoti.xml` and `asset-eoti.xml`
    merge with the base-game files (jungle was added by EOTI)."""
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VARIATION_VEGETATION_TREES_CUT</zType>
                <SingleAsset>ASSET_VEGETATION_TREES_CUT</SingleAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "assetVariation-eoti.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VARIATION_VEGETATION_JUNGLE_HILL</zType>
                <SingleAsset>ASSET_VEGETATION_JUNGLE_HILL</SingleAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "asset.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VEGETATION_TREES_CUT</zType>
                <zAsset>Prefabs/Features/Trees/ForestCut</zAsset>
            </Entry>
            """
        ),
    )
    _write(
        tmp_path / "asset-eoti.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VEGETATION_JUNGLE_HILL</zType>
                <zAsset>Prefabs/Resource/Jungle_01</zAsset>
            </Entry>
            """
        ),
    )
    result = load_vegetation_assets(tmp_path)
    output_names = sorted(v.output_name for v in result)
    assert output_names == ["JUNGLE_HILL", "TREES_CUT"]


def test_vegetation_missing_xml_dir_returns_empty(tmp_path: Path) -> None:
    """No `xml_dir` → empty list, no crash."""
    assert load_vegetation_assets(tmp_path / "nonexistent") == []


def test_vegetation_skips_candidates_with_no_asset(tmp_path: Path) -> None:
    """An aiRandomAssets candidate whose asset chain is broken is
    silently skipped; the remaining candidates still resolve."""
    _write(
        tmp_path / "assetVariation.xml",
        _wrap(
            """
            <Entry>
                <zType>ASSET_VARIATION_VEGETATION_TREES</zType>
                <aiRandomAssets>
                    <Pair><zIndex>ASSET_VEGETATION_TREES</zIndex><iValue>1</iValue></Pair>
                    <Pair><zIndex>ASSET_VEGETATION_TREES_DOES_NOT_EXIST</zIndex><iValue>1</iValue></Pair>
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
                <zType>ASSET_VEGETATION_TREES</zType>
                <zAsset>Prefabs/Features/Trees/Temperate_Tree_01_Cluster_Impostors</zAsset>
            </Entry>
            """
        ),
    )
    result = load_vegetation_assets(tmp_path)
    # Only one candidate resolved — single-prefab variation, no _NN
    # suffix on output_name.
    [veg] = result
    assert veg.output_name == "TREES"
    assert veg.prefab_name == "Temperate_Tree_01_Cluster_Impostors"
