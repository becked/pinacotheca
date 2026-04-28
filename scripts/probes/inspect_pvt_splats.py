"""Probe PVT splat MonoBehaviours for the runtime-composed cities investigation.

Resolves three open questions from docs/runtime-composed-cities.md:

  1. TypeTree availability: does UnityPy.read_typetree() return named fields
     for TerrainTexturePVTSplat, or do we need to hand-parse the binary?

  2. Texture inventory unknowns: walk every capital + urban prefab, dump the
     actual Texture2D names referenced by each splat plane (albedo, height,
     normal, metallic, roughness, alphamap).

  3. Atlas mode usage: across all instances, is `packInAtlas` ever true?

Read-only investigation; prints a report.
"""

from __future__ import annotations

import os
from collections import deque
from typing import Any

import UnityPy

from pinacotheca.extractor import find_game_data
from pinacotheca.prefab import _components_of, find_root_gameobject

# Capitals (7 sparse + 5 baked, for completeness) and urban tiles.
CAPITAL_PREFABS = [
    "Greece_Capital",
    "Persia_Capital",
    "Rome_Capital",
    "Carthage_Capital",
    "Babylonia_Capital",
    "Assyria_Capital",
    "Egypt_Capital",
    # Baked-geometry capitals — included to confirm they too have splat planes.
    "Maurya_Capital",
    "Tamil_Capital",
    "Yuezhi_Capital",
    "AksumCapitol",
    "Hittite_Capital",
]

URBAN_PREFABS = [
    "Greece_UrbanTile",
    "Persia_UrbanTile",
    "Rome_UrbanTile",
    "Carthage_UrbanTile",
    "Babylonia_UrbanTile",
    "Assyria_UrbanTile",
    "Egypt_UrbanTile",
    "Aksum_UrbanTile",
    "Hittite_UrbanTile",
    "India_UrbanTile",
]

# All component type names that look like splat MonoBehaviours, in case the
# urban/capital tile uses a sibling class.
SPLAT_TYPE_NAMES = {
    "TerrainTexturePVTSplat",
    "TerrainHeightSplat",
}


def texture_name(pptr: Any) -> str | None:
    """Resolve a Texture PPtr to the Texture2D's m_Name, or return None."""
    if pptr is None:
        return None
    try:
        if not bool(pptr):
            return None
    except Exception:
        return None
    try:
        obj = pptr.deref_parse_as_object()
        return getattr(obj, "m_Name", None)
    except Exception:
        return None


def walk_transform_tree(root_go: Any) -> list[Any]:
    """Return every GameObject in the prefab subtree (BFS via Transform)."""
    out: list[Any] = [root_go]
    t = None
    for pptr in _components_of(root_go):
        try:
            r = pptr.deref()
            if r.type.name == "Transform":
                t = pptr.deref_parse_as_object()
                break
        except Exception:
            pass
    if t is None:
        return out

    stack: deque = deque([t])
    while stack:
        node = stack.popleft()
        kids = getattr(node, "m_Children", None) or []
        for k in kids:
            try:
                if not bool(k):
                    continue
                child_t = k.deref_parse_as_object()
                go_pptr = getattr(child_t, "m_GameObject", None)
                if go_pptr and bool(go_pptr):
                    out.append(go_pptr.deref_parse_as_object())
                stack.append(child_t)
            except Exception:
                pass
    return out


def find_splat_components(go: Any) -> list[tuple[str, Any]]:
    """Return [(type_name, component_object_reader)] for splat components on go."""
    found: list[tuple[str, Any]] = []
    for pptr in _components_of(go):
        try:
            r = pptr.deref()
        except Exception:
            continue
        try:
            tn = r.type.name
        except Exception:
            continue
        if tn == "MonoBehaviour":
            # Need to read the script reference to get the actual class name.
            try:
                mb = pptr.deref_parse_as_object()
            except Exception:
                continue
            script_pptr = getattr(mb, "m_Script", None)
            cls_name = None
            if script_pptr is not None:
                try:
                    if bool(script_pptr):
                        script = script_pptr.deref_parse_as_object()
                        cls_name = getattr(script, "m_ClassName", None) or getattr(
                            script, "m_Name", None
                        )
                except Exception:
                    pass
            if cls_name in SPLAT_TYPE_NAMES:
                found.append((cls_name, r))
    return found


def probe_typetree(reader: Any) -> tuple[bool, dict[str, Any] | None, str]:
    """
    Try read_typetree() on a MonoBehaviour reader.

    Returns (success, tree_dict_or_None, diagnostic_string).
    """
    try:
        tree = reader.read_typetree()
        if isinstance(tree, dict) and len(tree) > 0:
            field_names = sorted(tree.keys())
            return True, tree, f"OK, {len(field_names)} fields: {field_names[:8]}..."
        return False, None, f"empty/invalid tree: type={type(tree).__name__}"
    except Exception as e:
        return False, None, f"raised {type(e).__name__}: {e}"


def main() -> None:
    game_data = find_game_data()
    if game_data is None:
        raise SystemExit("Game data not found")
    os.chdir(str(game_data))
    env = UnityPy.Environment()
    env.load_file(str(game_data / "resources.assets"))

    all_prefabs = [("CAPITAL", n) for n in CAPITAL_PREFABS] + [
        ("URBAN", n) for n in URBAN_PREFABS
    ]

    typetree_attempts: list[tuple[str, str, bool, str]] = []
    atlas_hits: list[tuple[str, str, str]] = []  # (prefab, plane_name, why)

    print("=" * 72)
    print("PVT SPLAT INVESTIGATION")
    print("=" * 72)

    for kind, prefab_name in all_prefabs:
        root = find_root_gameobject(env, prefab_name)
        if root is None:
            print(f"\n[{kind}] {prefab_name}: NOT FOUND in resources.assets")
            continue

        gos = walk_transform_tree(root)
        splat_planes: list[tuple[str, str, Any]] = []  # (plane_go_name, type, reader)
        for go in gos:
            for cls_name, reader in find_splat_components(go):
                go_name = getattr(go, "m_Name", "?")
                splat_planes.append((go_name, cls_name, reader))

        print(f"\n[{kind}] {prefab_name}: {len(splat_planes)} splat plane(s)")
        if not splat_planes:
            continue

        for i, (plane_name, cls, reader) in enumerate(splat_planes):
            ok, tree, diag = probe_typetree(reader)
            typetree_attempts.append((prefab_name, cls, ok, diag))
            print(f"  [{i}] plane='{plane_name}' class={cls}")
            print(f"      typetree: {diag}")
            if not ok or tree is None:
                continue

            # Texture references — tree dicts give us
            # {'m_FileID': ..., 'm_PathID': ...} per field, but we want
            # resolvable PPtrs, so re-parse the reader as an object.
            try:
                obj = reader.parse_as_object()
            except Exception:
                obj = None
            if obj is not None:
                tex_attrs = {
                    "albedoMap": getattr(obj, "albedoMap", None),
                    "normalMap": getattr(obj, "normalMap", None),
                    "metallicMap": getattr(obj, "metallicMap", None),
                    "roughnessMap": getattr(obj, "roughnessMap", None),
                    "alphaMap": getattr(obj, "alphaMap", None),
                    "heightmap": getattr(obj, "heightmap", None),
                    "rgbHeightmap": getattr(obj, "rgbHeightmap", None),
                    "albedoAtlas": getattr(obj, "albedoAtlas", None),
                    "alphaAtlas": getattr(obj, "alphaAtlas", None),
                    "normalMetalicRoughnessAtlas": getattr(
                        obj, "normalMetalicRoughnessAtlas", None
                    ),
                }
                for fname, pptr in tex_attrs.items():
                    name = texture_name(pptr)
                    if name:
                        print(f"      {fname}: {name}")

                # Atlas mode flag
                pack = getattr(obj, "packInAtlas", None)
                if pack:
                    print(f"      packInAtlas=True  atlasIndex={getattr(obj, 'atlasIndex', '?')}")
                    atlas_hits.append((prefab_name, plane_name, "packInAtlas=True"))

                # Other interesting scalars
                tint = getattr(obj, "albedoTint", None)
                ch = getattr(obj, "alphaMapChannel", None)
                tile = getattr(obj, "materialTiling", None)
                wuv = getattr(obj, "materialUseWorldUVs", None)
                ni = getattr(obj, "normalMapIntensity", None)
                if any(x is not None for x in (tint, ch, tile, wuv, ni)):
                    print(
                        f"      scalars: alphaMapChannel={ch} tiling={tile} useWorldUVs={wuv} normalIntensity={ni}"
                    )

    # ---- Summary ----
    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)

    n_tt_ok = sum(1 for _, _, ok, _ in typetree_attempts if ok)
    n_tt_total = len(typetree_attempts)
    print(f"\n#1 TypeTree: {n_tt_ok}/{n_tt_total} components parsed cleanly")
    fails = [(p, c, d) for p, c, ok, d in typetree_attempts if not ok]
    if fails:
        print("  Failures:")
        for p, c, d in fails[:10]:
            print(f"    {p} {c}: {d}")

    print(f"\n#3 packInAtlas usage: {len(atlas_hits)} hit(s)")
    for p, n, w in atlas_hits:
        print(f"    {p}/{n}: {w}")
    if not atlas_hits:
        print("    (none — atlas-mode branch can be deleted from plan)")


if __name__ == "__main__":
    main()
