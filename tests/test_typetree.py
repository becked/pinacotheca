"""TypeTree decode smoke test.

Replaces the historical hand-parser-vs-typetree parity gate (see
`docs/typetree-spike-findings.md` and `docs/typetree-migration.md` for
the migration history). With the hand parsers gone, the only invariant
left to verify is "decode succeeds on real game data" — if a game patch
renames or removes a serialized field, the per-class adapter will
KeyError loudly at this gate before any production extraction touches
it.

Skipped if the game install isn't available — same pattern as
`tests/test_terrain_index.py::test_real_xml_chain_resolves_28_tiles`.
"""

from __future__ import annotations

from typing import Any

import pytest

from pinacotheca.clutter_transforms import parse_clutter_transforms, script_class
from pinacotheca.extractor import find_game_data
from pinacotheca.pvt_splats import parse_height_splat, parse_pvt_splat
from pinacotheca.terrain_clutter_splat import parse_terrain_clutter_splat
from pinacotheca.typetree import setup_typetree_generator


@pytest.fixture(scope="module")
def env_with_typetree() -> Any:
    import UnityPy

    data_root = find_game_data()
    if data_root is None:
        pytest.skip("Game install not present")
    env = UnityPy.load(str(data_root))
    setup_typetree_generator(env, data_root=data_root)
    return env


@pytest.fixture(scope="module")
def monobehaviours_by_class(env_with_typetree: Any) -> dict[str, list[Any]]:
    targets = {
        "ClutterTransforms",
        "TerrainHeightSplat",
        "TerrainTexturePVTSplat",
        "TerrainClutterSplat",
    }
    by_class: dict[str, list[Any]] = {name: [] for name in targets}
    for obj in env_with_typetree.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            cls = script_class(obj)
        except Exception:
            continue
        if cls in by_class:
            by_class[cls].append(obj)
    return by_class


def test_decodes_clutter_transforms(
    env_with_typetree: Any, monobehaviours_by_class: dict[str, list[Any]]
) -> None:
    objs = monobehaviours_by_class["ClutterTransforms"]
    assert objs, "expected at least one ClutterTransforms instance"
    for obj in objs:
        result = parse_clutter_transforms(env_with_typetree, obj)
        assert result.models is not None  # smoke: shape is wired


def test_decodes_terrain_height_splat(
    env_with_typetree: Any, monobehaviours_by_class: dict[str, list[Any]]
) -> None:
    objs = monobehaviours_by_class["TerrainHeightSplat"]
    assert objs
    for obj in objs:
        parse_height_splat(env_with_typetree, obj)


def test_decodes_terrain_pvt_splat(
    env_with_typetree: Any, monobehaviours_by_class: dict[str, list[Any]]
) -> None:
    objs = monobehaviours_by_class["TerrainTexturePVTSplat"]
    assert objs
    for obj in objs:
        parse_pvt_splat(env_with_typetree, obj)


def test_decodes_terrain_clutter_splat(
    env_with_typetree: Any, monobehaviours_by_class: dict[str, list[Any]]
) -> None:
    objs = monobehaviours_by_class["TerrainClutterSplat"]
    assert objs
    for obj in objs:
        parse_terrain_clutter_splat(env_with_typetree, obj)
