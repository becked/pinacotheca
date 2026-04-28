"""
Sprite extraction from Unity asset bundles.

Uses UnityPy to extract sprites directly from Old World's game files.
"""

import gc
import os
import re
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pinacotheca.categories import CATEGORIES, categorize

# Exclusion patterns file (gitignored, contains patterns to skip)
EXCLUDE_PATTERNS_FILE = Path(__file__).parent.parent.parent / ".exclude-patterns"

# Texture name suffixes that mark a diffuse/albedo (color) texture.
# Order matters for stripping: longer suffixes first so `_diffuse` is removed
# before the shorter `_diff` substring would catch.
DIFFUSE_TEXTURE_SUFFIXES: tuple[str, ...] = (
    "_diffuse",
    "_basecolor",
    "_albedo",
    "_basemap",
    "_maintex",
    "_diff",
)


def build_texture_lookup(env: object) -> dict[str, object]:
    """
    Build a normalized-name -> Texture2D object lookup for diffuse textures.

    Recognizes Unity legacy (_Diffuse/_Albedo/_Diff), URP (_BaseMap),
    HDRP (_BaseColor), and main-texture (_MainTex) suffix conventions.
    The map key strips all known suffixes so callers can match using the
    mesh base name.

    Args:
        env: A loaded UnityPy.Environment

    Returns:
        Dict mapping the lowercased, suffix-stripped texture name to the
        original Texture2D object.
    """
    lookup: dict[str, object] = {}
    for obj in env.objects:  # type: ignore[attr-defined]
        if obj.type.name != "Texture2D":
            continue
        try:
            data = obj.read()
            name = getattr(data, "m_Name", "")
        except Exception:
            continue
        if not name:
            continue
        lower = name.lower()
        if not any(s in lower for s in DIFFUSE_TEXTURE_SUFFIXES):
            continue
        base = lower
        for suf in DIFFUSE_TEXTURE_SUFFIXES:
            base = base.replace(suf, "")
        lookup[base] = obj
    return lookup


def load_exclusion_pattern() -> re.Pattern[str] | None:
    """
    Load exclusion patterns from .exclude-patterns file if it exists.

    The file should contain regex patterns (one per line, or pipe-separated).
    Lines starting with # are comments. Empty lines are ignored.

    Returns:
        Compiled regex pattern, or None if no exclusions
    """
    if not EXCLUDE_PATTERNS_FILE.exists():
        return None

    patterns: list[str] = []
    for line in EXCLUDE_PATTERNS_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            # Support both one-per-line and pipe-separated
            patterns.extend(p.strip() for p in line.split("|") if p.strip())

    if not patterns:
        return None

    # Combine into single pattern with word boundaries for safety
    combined = "|".join(patterns)
    return re.compile(combined, re.IGNORECASE)


if TYPE_CHECKING:
    from UnityPy import Environment

# Platform-specific game data paths
GAME_DATA_MAC = (
    Path.home()
    / "Library/Application Support/Steam/steamapps/common/Old World/OldWorld.app/Contents/Resources/Data"
)
GAME_DATA_WIN = Path("C:/Program Files (x86)/Steam/steamapps/common/Old World/OldWorld_Data")


def find_game_data() -> Path | None:
    """
    Auto-detect the game data directory.

    Returns:
        Path to the game's Data directory, or None if not found
    """
    if GAME_DATA_MAC.exists():
        return GAME_DATA_MAC
    if GAME_DATA_WIN.exists():
        return GAME_DATA_WIN
    return None


def extract_sprites(
    game_data: Path | None = None,
    output_dir: Path | None = None,
    *,
    verbose: bool = True,
) -> dict[str, int]:
    """
    Extract all sprites from Old World assets.

    Args:
        game_data: Path to game's Data directory (auto-detected if None)
        output_dir: Where to save extracted sprites (defaults to ./extracted)
        verbose: Print progress messages

    Returns:
        Dict mapping category names to count of sprites extracted

    Raises:
        FileNotFoundError: If game data directory not found
        ImportError: If UnityPy is not installed
    """
    try:
        import UnityPy
    except ImportError:
        print("ERROR: UnityPy not installed", file=sys.stderr)
        print("Install with: pip install UnityPy Pillow", file=sys.stderr)
        raise

    # Resolve paths
    if game_data is None:
        game_data = find_game_data()
    if game_data is None or not game_data.exists():
        raise FileNotFoundError(
            f"Could not find Old World game data!\n"
            f"Expected locations:\n"
            f"  macOS: {GAME_DATA_MAC}\n"
            f"  Windows: {GAME_DATA_WIN}"
        )

    if output_dir is None:
        output_dir = Path.cwd() / "extracted"

    if verbose:
        print("=" * 60)
        print("Old World Sprite Extractor")
        print("=" * 60)
        print(f"\nGame data: {game_data}")
        print(f"Output: {output_dir}")

    # Create output directories
    sprites_dir = output_dir / "sprites"
    for cat in CATEGORIES:
        (sprites_dir / cat).mkdir(parents=True, exist_ok=True)

    # Clean up stale category folders (from previous extractions with different categories)
    if sprites_dir.exists():
        valid_categories = set(CATEGORIES.keys())
        for item in sprites_dir.iterdir():
            if item.is_dir() and item.name not in valid_categories:
                if verbose:
                    print(f"Removing stale category folder: {item.name}/")
                shutil.rmtree(item)

    # CRITICAL: Change to Data directory so UnityPy can find .resS files
    original_cwd = os.getcwd()
    os.chdir(str(game_data))

    try:
        # Load exclusion patterns (from gitignored .exclude-patterns file)
        exclude_pattern = load_exclusion_pattern()
        excluded_count = 0

        if verbose:
            if exclude_pattern:
                print("\nExclusion patterns loaded from .exclude-patterns")
            print("\nLoading asset index...")

        env: Environment = UnityPy.Environment()
        env.load_file(str(game_data / "resources.assets"))

        # Filter to just Sprite objects
        sprites = [obj for obj in env.objects if obj.type.name == "Sprite"]
        total = len(sprites)

        if verbose:
            print(f"Found {total:,} sprites\n")
            print("Extracting sprites...")

        counts: dict[str, int] = dict.fromkeys(CATEGORIES, 0)
        errors = 0

        for i, obj in enumerate(sprites):
            try:
                data = obj.read()
                name = getattr(data, "m_Name", "")

                if name:
                    # Skip excluded patterns
                    if exclude_pattern and exclude_pattern.search(name):
                        excluded_count += 1
                        del data
                        continue

                    img = data.image
                    if img:
                        cat = categorize(name)

                        # Large uncategorized images are backgrounds
                        if cat == "other" and img.width >= 1024:
                            cat = "backgrounds"

                        out_path = sprites_dir / cat / f"{name}.png"

                        if not out_path.exists():
                            img.save(out_path)
                            counts[cat] += 1

                        del img
                del data

            except Exception:
                errors += 1

            # Progress and memory management
            if verbose and (i + 1) % 500 == 0:
                gc.collect()
                extracted = sum(counts.values())
                print(f"  Progress: {i + 1:,}/{total:,} | Extracted: {extracted:,}")

        # Summary
        total_extracted = sum(counts.values())

        if verbose:
            print("\n" + "=" * 60)
            print("EXTRACTION COMPLETE")
            print("=" * 60)
            print(f"Total sprites extracted: {total_extracted:,}")
            if excluded_count > 0:
                print(f"Excluded by pattern: {excluded_count:,}")
            print(f"Errors: {errors:,}")
            print("\nBy category:")
            for cat, count in sorted(counts.items(), key=lambda x: -x[1]):
                if count > 0:
                    print(f"  {cat}: {count:,}")
            print(f"\nOutput saved to: {sprites_dir}")

        return counts

    finally:
        os.chdir(original_cwd)


# Curated list of unit meshes to extract
# Format: (mesh_name, output_name)
UNIT_MESHES: list[tuple[str, str]] = [
    # Infantry - Archers
    ("Archer_GEO", "ARCHER"),
    ("Akkadian_Archer_GEO", "AKKADIAN_ARCHER"),
    ("Cimmerian Archer", "CIMMERIAN_ARCHER"),
    ("KushiteArcherlvl1", "KUSHITE_ARCHER_LVL1"),
    ("KushiteArcherlvl2", "KUSHITE_ARCHER_LVL2"),
    ("Longbowman_GEO", "LONGBOWMAN"),
    ("Crossbowman_GEO", "CROSSBOWMAN"),
    ("Slinger_GEO", "SLINGER"),
    # Infantry - Melee
    ("Warrior_geo", "WARRIOR"),
    ("Spearman_GEO", "SPEARMAN"),
    ("Axeman_GEO", "AXEMAN"),
    ("Maceman_GEO", "MACEMAN"),
    ("Pikeman_GEO", "PIKEMAN"),
    ("Militia_GEO", "MILITIA"),
    ("Scout_GEO", "SCOUT"),
    ("Legionary_GEO", "LEGIONARY"),
    ("Swordman_Body", "SWORDSMAN"),
    ("Hopelite_GEO", "HOPLITE"),
    ("Huscarl_GEO", "HUSCARL"),
    ("EliteHuscarl_GEO", "ELITE_HUSCARL"),
    ("Javelineer_GEO", "JAVELINEER"),
    ("Elite_Javelineer_GEO", "ELITE_JAVELINEER"),
    ("Gaesata_GEO", "GAESATA"),
    ("Elite_Gaestata__GEO", "ELITE_GAESATA"),
    ("ClubThrower_GEO", "CLUB_THROWER"),
    ("Elite_ClubThrower_GEO", "ELITE_CLUB_THROWER"),
    ("Conscript_GEO", "CONSCRIPT"),
    ("Phalangite", "PHALANGITE"),
    ("Hastatus", "HASTATUS"),
    ("Peltast_GEO", "PELTAST"),
    # Cavalry - Ranged
    ("Horse_Archer_GEO", "HORSE_ARCHER"),
    ("Camel_Archer_GEO", "CAMEL_ARCHER"),
    ("Cataphract_Archer_GEO", "CATAPHRACT_ARCHER"),
    # Cavalry - Melee
    ("Horseman_GEO", "HORSEMAN"),
    ("Cataphract_GEO", "CATAPHRACT"),
    ("Palton_Cavalry_GEO", "PALTON_CAVALRY"),
    ("Libyan_Cavalry_GEO", "LIBYAN_CAVALRY"),
    ("Elite_Libyan_Cavalry_GEO", "ELITE_LIBYAN_CAVALRY"),
    ("Kushite_Cavalry_GEO", "KUSHITE_CAVALRY"),
    ("Amazon_Cavalry_Horse_GEO", "AMAZON_CAVALRY"),
    ("Elite_Amazon_Cavalry_GEO", "ELITE_AMAZON_CAVALRY"),
    ("YeuzhiUU2_KushanCavalry_GEO", "KUSHAN_CAVALRY"),
    ("Kushite_Cavalry_GEO", "MOUNTED_LANCER"),
    # Chariots
    ("Chariot_GEO", "CHARIOT"),
    ("Light Chariot", "LIGHT_CHARIOT"),
    ("chariot", "CHARIOT_ALT"),
    ("chariot_lv2", "CHARIOT_LVL2"),
    # Elephants
    ("War_Elephant_GEO", "WAR_ELEPHANT"),
    ("Turreted_elephant_GEO", "TURRETED_ELEPHANT"),
    ("African_Elephant_GEO", "AFRICAN_ELEPHANT"),
    ("MauryaUU1_AssultElephant_GEO", "MAURYA_ASSAULT_ELEPHANT"),
    ("Maurya_UU2_Armoured_Elephant_GEO", "MAURYA_ARMOURED_ELEPHANT"),
    ("TamilUU1JavelinElephant_GEO", "TAMIL_JAVELIN_ELEPHANT"),
    ("TamilUU2ArcherElephant_GEO", "TAMIL_ARCHER_ELEPHANT"),
    # Siege
    ("Ballista_GEO", "BALLISTA"),
    ("Battering_Ram_GEO", "BATTERING_RAM"),
    ("Siege_Tower_GEO", "SIEGE_TOWER"),
    ("Catapult_GEO", "CATAPULT"),
    ("Onager_GEO", "ONAGER"),
    ("Polybolos_GEO", "POLYBOLOS"),
    ("mangonel_GEO", "MANGONEL"),
    # Naval
    ("Bireme_GEO", "BIREME"),
    ("Trireme_GEO", "TRIREME"),
    ("Dromon_GEO", "DROMON"),
    # Barbarians/Special
    ("Barbarian_Raider_GEO", "BARBARIAN_RAIDER"),
    ("Barbarian_Elite_GEO", "BARBARIAN_ELITE"),
    ("Caravan_GEO", "CARAVAN"),
    # Aksum
    ("AksumUU1DmtWarrior_GEO", "AKSUM_DMT_WARRIOR"),
    ("AksumUU2ShotelaiWarrior_GEO", "AKSUM_SHOTELAI_WARRIOR"),
    ("KushiteArcherlvl1", "MEDJAY_ARCHER"),
    ("KushiteArcherlvl2", "BEJA_ARCHER"),
    # Nomads
    ("Nomad_Raider_GEO", "NOMAD_RAIDER"),
    ("Nomad_Skirmisher_GEO", "NOMAD_SKIRMISHER"),
    ("Nomad_Warlord_GEO", "NOMAD_WARLORD"),
    ("Elite_Nomad_Marauder_GEO", "ELITE_NOMAD_MARAUDER"),
    ("Elite_Nomad_Skirmisher_GEO", "ELITE_NOMAD_SKIRMISHER"),
    ("Elite_Nomad_Warlord_GEO", "ELITE_NOMAD_WARLORD"),
    # Skirmishers/Warlords
    ("Elite_Skirmisher_GEO", "ELITE_SKIRMISHER"),
    ("Elite_Warlord_GEO", "ELITE_WARLORD"),
    ("Elite_Maurader_GEO", "ELITE_MARAUDER"),
    # Yuezhi
    ("YuezchiUU1_SteppeRider_GEO", "STEPPE_RIDER"),
    ("YueezhiUU3_KushanWarlord_GEO", "KUSHAN_WARLORDS"),
    # Non-combat
    ("Settler_GEO2", "SETTLER"),
    ("Worker_GEO", "WORKER"),
    # Religious disciples
    ("Disciple_Buddhist_GEO", "DISCIPLE_BUDDHIST"),
    ("Disciple_Hindu_GEO", "DISCIPLE_HINDU"),
    ("Jewish_Disciple_GEO", "DISCIPLE_JEWISH"),
    ("Manichean_Disciple_GEO", "DISCIPLE_MANICHEAN"),
]


def extract_unit_meshes(
    game_data: Path | None = None,
    output_dir: Path | None = None,
    *,
    verbose: bool = True,
) -> dict[str, int]:
    """
    Extract 3D unit meshes and render them to 2D images.

    Runs AFTER 2D sprite extraction. Does not affect existing sprites.
    Output files are named UNIT_3D_{name}.png to distinguish from 2D sprites.

    Args:
        game_data: Path to game's Data directory (auto-detected if None)
        output_dir: Where to save rendered images (defaults to ./extracted)
        verbose: Print progress messages

    Returns:
        Dict with 'rendered' and 'skipped' counts

    Raises:
        FileNotFoundError: If game data directory not found
    """
    try:
        import UnityPy
    except ImportError:
        print("ERROR: UnityPy not installed", file=sys.stderr)
        raise

    try:
        from pinacotheca.renderer import render_mesh_to_image
    except ImportError as e:
        if verbose:
            print(f"WARNING: 3D rendering not available ({e})", file=sys.stderr)
            print("Skipping mesh extraction. Install moderngl for 3D support.", file=sys.stderr)
        return {"rendered": 0, "skipped": 0}

    # Resolve paths
    if game_data is None:
        game_data = find_game_data()
    if game_data is None or not game_data.exists():
        raise FileNotFoundError("Could not find Old World game data!")

    if output_dir is None:
        output_dir = Path.cwd() / "extracted"

    sprites_dir = output_dir / "sprites" / "units"
    sprites_dir.mkdir(parents=True, exist_ok=True)

    if verbose:
        print("\n" + "=" * 60)
        print("3D Unit Mesh Extraction")
        print("=" * 60)

    # Load exclusion patterns
    exclude_pattern = load_exclusion_pattern()
    excluded_count = 0

    # Change to game data directory for UnityPy
    original_cwd = os.getcwd()
    os.chdir(str(game_data))

    try:
        if verbose:
            if exclude_pattern:
                print("Exclusion patterns loaded from .exclude-patterns")
            print("Loading assets...")

        env = UnityPy.Environment()
        env.load_file(str(game_data / "resources.assets"))

        mesh_lookup: dict[str, Any] = {}
        unreadable = 0

        for obj in env.objects:
            try:
                if obj.type.name == "Mesh":
                    data = obj.read()
                    name = getattr(data, "m_Name", "")
                    if name:
                        mesh_lookup[name] = obj
            except Exception:
                unreadable += 1

        texture_lookup: dict[str, Any] = build_texture_lookup(env)

        if verbose:
            print(f"Found {len(mesh_lookup)} meshes, {len(texture_lookup)} diffuse textures")
            if unreadable:
                print(f"Skipped {unreadable} unreadable objects")
            print(f"Processing {len(UNIT_MESHES)} unit meshes...\n")

        rendered = 0
        skipped = 0

        for mesh_name, output_name in UNIT_MESHES:
            # Skip excluded patterns
            if exclude_pattern and exclude_pattern.search(output_name):
                excluded_count += 1
                if verbose:
                    print(f"  [EXCLUDED] {output_name}")
                continue

            out_path = sprites_dir / f"UNIT_3D_{output_name}.png"

            # Skip if already exists
            if out_path.exists():
                if verbose:
                    print(f"  [EXISTS] {output_name}")
                continue

            # Find mesh
            if mesh_name not in mesh_lookup:
                if verbose:
                    print(f"  [SKIP] {output_name} - mesh not found")
                skipped += 1
                continue

            # Find texture (try various name patterns)
            texture_obj = None
            search_names = [
                mesh_name.lower().replace("_geo", "").replace(" ", "").replace("_", ""),
                mesh_name.lower().replace("_geo", "").replace(" ", "_"),
                mesh_name.lower().replace(" ", ""),
                output_name.lower(),
            ]

            for search in search_names:
                for tex_name, tex_obj in texture_lookup.items():
                    if search in tex_name or tex_name in search:
                        texture_obj = tex_obj
                        break
                if texture_obj:
                    break

            if texture_obj is None:
                if verbose:
                    print(f"  [SKIP] {output_name} - texture not found")
                skipped += 1
                continue

            # Extract and render
            try:
                mesh_data = mesh_lookup[mesh_name].read()
                obj_data = mesh_data.export()

                tex_data = texture_obj.read()
                texture_image = tex_data.image

                if obj_data and texture_image:
                    img = render_mesh_to_image(obj_data, texture_image)
                    img.save(out_path, optimize=False)
                    rendered += 1
                    if verbose:
                        print(f"  [OK] {output_name}")

                    # Clean up
                    del img
                    del texture_image

                gc.collect()

            except Exception as e:
                if verbose:
                    print(f"  [ERROR] {output_name} - {e}")
                skipped += 1

        if verbose:
            print("\n" + "=" * 60)
            print("3D EXTRACTION COMPLETE")
            print("=" * 60)
            print(f"Rendered: {rendered}")
            if excluded_count > 0:
                print(f"Excluded by pattern: {excluded_count}")
            print(f"Skipped: {skipped}")
            print(f"Output: {sprites_dir}")

        return {"rendered": rendered, "skipped": skipped, "excluded": excluded_count}

    finally:
        os.chdir(original_cwd)


# Improvements not represented in improvement.xml that we still want to
# render. Currently only the four pyramid construction stages, used by the
# wonder-build animation but not associated with a tile-improvement entry.
# Format: (prefab_root_gameobject_name, z_icon_name).
SUPPLEMENTAL_PREFABS: list[tuple[str, str]] = [
    ("Pyramid_lvl_1", "PYRAMID_LVL_1"),
    ("Pyramid_lvl_2", "PYRAMID_LVL_2"),
    ("Pyramid_lvl_3", "PYRAMID_LVL_3"),
    ("Pyramid_lvl_4", "PYRAMID_LVL_4"),
]

# Prefabs whose diffuse-texture decode segfaults UnityPy's C-level image
# reader (e.g., unsupported texture format combination). Skipped entirely
# rather than crashing the whole extraction. SIGSEGV bypasses Python's
# try/except, so the blacklist is checked BEFORE any prefab-walking.
# A more principled fix is subprocess-per-asset isolation; deferred until
# the list grows past a handful of entries.
PREFAB_DECODE_BLACKLIST: frozenset[str] = frozenset(
    {
        "Fort",  # Material.001_Diff crashes Texture2D.image
    }
)


def extract_improvement_meshes(
    game_data: Path | None = None,
    output_dir: Path | None = None,
    *,
    verbose: bool = True,
) -> dict[str, int]:
    """
    Extract 3D improvement (building) meshes and render them to 2D PNGs.

    The list of improvements to render is discovered from the game's XML
    chain (improvement.xml → assetVariation.xml → asset.xml; see
    `pinacotheca.asset_index`). Output filenames use the canonical
    `zIconName` (e.g. `IMPROVEMENT_3D_LIBRARY.png`), keyed for downstream
    consumers like per-ankh that look up renders by zIconName.

    Plus a small `SUPPLEMENTAL_PREFABS` list for prefabs that aren't
    represented in `improvement.xml` (currently only the four pyramid
    construction stages).

    Args:
        game_data: Path to game's Data directory (auto-detected if None)
        output_dir: Where to save rendered images (defaults to ./extracted)
        verbose: Print progress messages

    Returns:
        Dict with 'rendered', 'skipped', and 'excluded' counts

    Raises:
        FileNotFoundError: If game data directory not found
    """
    try:
        import UnityPy
    except ImportError:
        print("ERROR: UnityPy not installed", file=sys.stderr)
        raise

    try:
        from pinacotheca.renderer import render_mesh_to_image
    except ImportError as e:
        if verbose:
            print(f"WARNING: 3D rendering not available ({e})", file=sys.stderr)
            print(
                "Skipping improvement extraction. Install moderngl for 3D support.",
                file=sys.stderr,
            )
        return {"rendered": 0, "skipped": 0, "excluded": 0}

    from pinacotheca.asset_index import (
        load_capital_assets,
        load_improvement_assets,
        load_urban_assets,
    )
    from pinacotheca.clutter_transforms import (
        clutter_to_prefab_parts,
        find_clutter_transforms_in_prefab,
    )
    from pinacotheca.prefab import (
        bake_to_obj,
        drop_splat_meshes,
        find_diffuse_for_prefab,
        find_ground_y,
        find_root_gameobject,
        strip_plinth_from_obj,
        walk_prefab,
    )

    if game_data is None:
        game_data = find_game_data()
    if game_data is None or not game_data.exists():
        raise FileNotFoundError("Could not find Old World game data!")

    if output_dir is None:
        output_dir = Path.cwd() / "extracted"

    sprites_dir = output_dir / "sprites" / "improvements"
    sprites_dir.mkdir(parents=True, exist_ok=True)

    # Resolve the XML chain. Reference/XML/Infos lives at the game's
    # install root, which is several directories up from the Data dir
    # (deeper on macOS where Data is inside OldWorld.app/Contents/Resources/).
    # Walk up until we find it.
    xml_dir: Path | None = None
    for ancestor in [game_data, *game_data.parents]:
        candidate = ancestor / "Reference" / "XML" / "Infos"
        if candidate.is_dir():
            xml_dir = candidate
            break
    if xml_dir is None:
        raise FileNotFoundError(f"Could not locate Reference/XML/Infos starting from {game_data}")
    improvements = load_improvement_assets(xml_dir)
    capitals = load_capital_assets(xml_dir)
    urbans = load_urban_assets(xml_dir)
    # Build the full job list: (prefab_name, output_name) pairs. All sources
    # flow into the same render path; capitals/urban tiles are added with
    # their already-prefix-stripped canonical names (MAURYA_CAPITAL,
    # GREECE_URBAN, etc).
    jobs: list[tuple[str, str]] = [
        (a.prefab_name, a.z_icon_name.removeprefix("IMPROVEMENT_")) for a in improvements
    ]
    jobs.extend((c.prefab_name, c.z_icon_name) for c in capitals)
    jobs.extend((u.prefab_name, u.z_icon_name) for u in urbans)
    jobs.extend(SUPPLEMENTAL_PREFABS)

    # Stale-PNG cleanup: anything not in the new canonical set goes.
    canonical_filenames = {f"IMPROVEMENT_3D_{out}.png" for _, out in jobs}
    stale_count = 0
    for existing in sprites_dir.glob("IMPROVEMENT_3D_*.png"):
        if existing.name not in canonical_filenames:
            existing.unlink()
            stale_count += 1

    if verbose:
        print("\n" + "=" * 60)
        print("3D Improvement Mesh Extraction")
        print("=" * 60)
        print(f"Loading XML chain from {xml_dir}")
        print(
            f"Discovered {len(improvements)} improvements + {len(capitals)} capitals "
            f"+ {len(urbans)} urban tiles via XML, +{len(SUPPLEMENTAL_PREFABS)} "
            "supplemental prefabs"
        )
        if stale_count:
            print(f"Removed {stale_count} stale PNG(s) from previous extraction")

    exclude_pattern = load_exclusion_pattern()
    excluded_count = 0

    original_cwd = os.getcwd()
    os.chdir(str(game_data))

    try:
        if verbose:
            if exclude_pattern:
                print("Exclusion patterns loaded from .exclude-patterns")
            print("Loading Unity assets...")

        env = UnityPy.Environment()
        # globalgamemanagers.assets carries the MonoScript objects that the
        # ClutterTransforms walker resolves via m_Script PPtrs (file_id=1).
        # Load it before resources.assets so its objects are reachable, but
        # path-id collisions stay isolated: clutter mesh/material lookups
        # are explicitly scoped to resources.assets via
        # `clutter_transforms.find_object_by_path_id`.
        env.load_file(str(game_data / "globalgamemanagers.assets"))
        env.load_file(str(game_data / "resources.assets"))

        rendered = 0
        skipped_no_prefab = 0
        skipped_no_texture = 0
        skipped_no_geometry = 0
        render_errors = 0

        for prefab_name, output_name in jobs:
            if exclude_pattern and exclude_pattern.search(output_name):
                excluded_count += 1
                if verbose:
                    print(f"  [EXCLUDED] {output_name}")
                continue

            out_path = sprites_dir / f"IMPROVEMENT_3D_{output_name}.png"
            if out_path.exists():
                if verbose:
                    print(f"  [EXISTS] {output_name}")
                continue

            if prefab_name in PREFAB_DECODE_BLACKLIST:
                if verbose:
                    print(
                        f"  [SKIP] {output_name} - prefab '{prefab_name}' blacklisted "
                        "(known UnityPy texture-decode segfault)"
                    )
                skipped_no_geometry += 1
                continue

            root_go = find_root_gameobject(env, prefab_name)
            if root_go is None:
                if verbose:
                    print(f"  [SKIP] {output_name} - prefab '{prefab_name}' not found in assets")
                skipped_no_prefab += 1
                continue

            parts = walk_prefab(root_go)
            # Drop lower-LOD duplicates first (we render LOD0 only).
            lod_kept = [p for p in parts if not _is_lower_lod_part(p)]
            # Sample the terrain ground stamp BEFORE dropping splat parts.
            # The SplatHeightDefault plane's Y is the game's true ground
            # line — preferred over the density heuristic. None when the
            # prefab has no ground stamp; strip_plinth_from_obj then falls
            # back to its density heuristic.
            cut_y_override = find_ground_y(lod_kept)
            # Drop splat-shader meshes (heightmaps, alphamaps, water surfaces)
            # by material name.
            kept = drop_splat_meshes(lod_kept)

            # Augment with ClutterTransforms-driven instance parts. Sparse
            # capitals (Greece/Rome/Persia/Carthage/Babylonia/Assyria/Egypt)
            # carry their building geometry here rather than in MeshFilter
            # leaves; some urban tiles and improvements may too. This is
            # always-additive — prefabs without a ClutterTransforms produce
            # an empty list and behavior is unchanged.
            clutter_parts: list[Any] = []
            try:
                cts = find_clutter_transforms_in_prefab(root_go)
            except Exception as e:
                if verbose:
                    print(f"  [WARN] {output_name} - clutter walk failed: {e}")
                cts = []
            for parsed_ct, parent_world in cts:
                try:
                    expanded = clutter_to_prefab_parts(env, parsed_ct, parent_world)
                except NotImplementedError as e:
                    if verbose:
                        print(f"  [WARN] {output_name} - clutter feature unsupported: {e}")
                    continue
                clutter_parts.extend(expanded)
            if cts and verbose:
                total_models = sum(len(p.models) for p, _ in cts)
                total_instances = sum(
                    sum(len(m.instances) for m in p.models) for p, _ in cts
                )
                print(
                    f"  [CT] {output_name} - {len(cts)} ClutterTransforms, "
                    f"{total_models} models, {total_instances} instances"
                )

            combined = kept + clutter_parts
            if not combined:
                if verbose:
                    print(f"  [SKIP] {output_name} - no usable mesh parts in prefab")
                skipped_no_geometry += 1
                continue

            obj_str = bake_to_obj(combined, pre_rotation_y_deg=180.0)
            obj_str = strip_plinth_from_obj(obj_str, cut_y_override=cut_y_override)
            tex_img = find_diffuse_for_prefab(combined)
            if tex_img is None:
                if verbose:
                    print(f"  [SKIP] {output_name} - no diffuse texture in prefab materials")
                skipped_no_texture += 1
                continue
            if not obj_str:
                if verbose:
                    print(f"  [SKIP] {output_name} - empty bake output")
                skipped_no_geometry += 1
                continue

            try:
                img = render_mesh_to_image(obj_str, tex_img, force_upright=True)
                img.save(out_path, optimize=False)
                rendered += 1
                if verbose:
                    print(f"  [OK] {output_name} ({len(combined)} parts)")
                del img
                del tex_img
                gc.collect()
            except Exception as e:
                if verbose:
                    print(f"  [ERROR] {output_name} - render failed: {e}")
                render_errors += 1

        skipped = skipped_no_prefab + skipped_no_texture + skipped_no_geometry + render_errors

        if verbose:
            print("\n" + "=" * 60)
            print("3D IMPROVEMENT EXTRACTION COMPLETE")
            print("=" * 60)
            print(f"Rendered: {rendered}")
            print(
                f"Skipped: {skipped} "
                f"(no-prefab={skipped_no_prefab}, no-texture={skipped_no_texture}, "
                f"no-geometry={skipped_no_geometry}, render-errors={render_errors})"
            )
            if excluded_count > 0:
                print(f"Excluded by pattern: {excluded_count}")
            print(f"Output: {sprites_dir}")

        return {"rendered": rendered, "skipped": skipped, "excluded": excluded_count}

    finally:
        os.chdir(original_cwd)


def _is_lower_lod_part(part: Any) -> bool:
    """True if the part's mesh name ends in `_LOD1` or `_LOD2`."""
    try:
        mesh = part.mesh_obj.deref_parse_as_object()
        name = getattr(mesh, "m_Name", "") or ""
    except Exception:
        return False
    return bool(re.search(r"_LOD[12]$", name, flags=re.IGNORECASE))
