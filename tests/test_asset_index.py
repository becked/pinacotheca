"""Synthetic-XML tests for asset_index.

These tests use temporary directories with hand-written XML strings —
no real game files. They verify the chain resolution semantics so we
don't depend on the game install for CI.
"""

from __future__ import annotations

from pathlib import Path

from pinacotheca.asset_index import ImprovementAsset, load_improvement_assets


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
