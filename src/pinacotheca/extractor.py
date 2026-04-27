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


# Curated list of building/improvement meshes to render in 3D.
# Format: (mesh_name, output_name)
# Output filenames use the IMPROVEMENT_3D_<NAME>.png pattern so they classify
# into the existing 'improvements' category alongside 2D improvement icons.
IMPROVEMENT_MESHES: list[tuple[str, str]] = [
    # Civic / military buildings (LOD0 high-detail variants)
    ("Library_LOD0", "LIBRARY"),
    ("Barracks_LOD0", "BARRACKS"),
    ("Granary_LOD0", "GRANARY"),
    ("Hamlet_LOD0", "HAMLET"),
    ("Village_LOD0", "VILLAGE"),
    ("Citadel_LOD0", "CITADEL"),
    ("Garrison_LOD0", "GARRISON"),
    ("Stronghold_LOD0", "STRONGHOLD"),
    ("Watermill_LOD0", "WATERMILL"),
    ("lumbermill_geo_LOD0", "LUMBERMILL"),
    ("ministry_LOD0", "MINISTRY"),
    ("odeon_LOD0", "ODEON"),
    ("range_LOD0", "RANGE"),
    # Religious - temples & cathedrals & monasteries
    ("ChristianTemple_LOD0", "CHRISTIAN_TEMPLE"),
    ("Christian_Cathedral_LOD0", "CHRISTIAN_CATHEDRAL"),
    ("Christian_Monastery_LOD0", "CHRISTIAN_MONASTERY"),
    ("Jewish_Temple_LOD0", "JEWISH_TEMPLE"),
    ("Jewish_Monastery_LOD0", "JEWISH_MONASTERY"),
    ("Manichean_Temple_LOD0", "MANICHEAN_TEMPLE"),
    ("Manichean_Cathedral_LOD0", "MANICHEAN_CATHEDRAL"),
    ("Manichean_Monastery_low_LOD0", "MANICHEAN_MONASTERY"),
    ("Zoroastrian_Cathedral_LOD0", "ZOROASTRIAN_CATHEDRAL"),
    ("Zoroastrian_Monastery_LOD0", "ZOROASTRIAN_MONASTERY"),
    # Religious - shrines
    ("Fire_Shrine_LOD0", "FIRE_SHRINE"),
    ("Hunting_Shrine_LOD0", "HUNTING_SHRINE"),
    ("Healing_Shrine_LOD0", "HEALING_SHRINE"),
    ("Kingship_Shrine_LOD0", "KINGSHIP_SHRINE"),
    ("Love_Shrine_LOD0", "LOVE_SHRINE"),
    ("Sun_Shrine_LOD0", "SUN_SHRINE"),
    ("Underworld_Shrine_LOD0", "UNDERWORLD_SHRINE"),
    ("War_Shrine_LOD0", "WAR_SHRINE"),
    ("WaterShrine_LOD0", "WATER_SHRINE"),
    ("HearthShrineSoot_LOD0", "HEARTH_SHRINE"),
    ("wisdomShrine_LOD0", "WISDOM_SHRINE"),
    # Named non-LOD improvements (the .001-resolver picks bare name first,
    # then lowest-numbered duplicate). Some of these may be composite prefabs;
    # if so they will appear exploded until Phase C lands.
    ("Academy", "ACADEMY"),
    ("Market", "MARKET"),
    ("Palace", "PALACE"),
    ("Coldbaths", "COLDBATHS"),
    ("Courthouse_low", "COURTHOUSE"),
    ("Obelisk", "OBELISK"),
    ("Wall", "WALL"),
    ("Tower", "TOWER"),
    ("TheaterPompey", "THEATER_POMPEY"),
    ("RoyalLibraryRT", "ROYAL_LIBRARY"),
    # Rural improvements (non-LOD; .001-resolver picks bare name when present).
    # Some lack clean diffuse textures and will skip.
    ("Pasture", "PASTURE"),
    ("Outpost", "OUTPOST"),
    ("Encampmant", "ENCAMPMENT"),  # game asset retains misspelling
    ("QuarryStone", "QUARRY"),
    ("Mine-unique04", "MINE"),
    ("BrickPile", "BRICKWORKS"),
]


def _resolve_mesh_variant(
    mesh_lookup: dict[str, Any],
    base: str,
) -> str | None:
    """
    Resolve a curated mesh name against the actual mesh lookup.

    Picks the bare-named mesh if present; otherwise the lowest-numbered
    `.001`/`.002` duplicate. Returns the resolved key or None.
    """
    if base in mesh_lookup:
        return base
    suffixed = sorted(n for n in mesh_lookup if n.startswith(base + "."))
    return suffixed[0] if suffixed else None


def _find_texture(
    texture_lookup: dict[str, Any],
    mesh_name: str,
    output_name: str,
) -> Any | None:
    """
    Find a diffuse texture for a building mesh.

    Tries several name normalizations against the suffix-stripped texture
    lookup. Returns the Texture2D object or None.
    """
    base = re.sub(r"_LOD\d+$", "", mesh_name, flags=re.IGNORECASE).lower().strip()
    fully_norm = re.sub(r"[^a-z0-9]", "", base)

    candidates: list[str] = [
        base,  # 'library' or 'christian_temple'
        base.replace(" ", "_"),
        base.replace(" ", ""),
        fully_norm,  # 'christiantemple', for cross-underscore matches
        output_name.lower(),
    ]

    seen: set[str] = set()
    for cand in candidates:
        if not cand or cand in seen:
            continue
        seen.add(cand)
        if cand in texture_lookup:
            return texture_lookup[cand]
        for tex_key, tex_obj in texture_lookup.items():
            tex_norm = re.sub(r"[^a-z0-9]", "", tex_key)
            if cand == tex_norm or (cand and cand in tex_norm) or (tex_norm and tex_norm in cand):
                return tex_obj
    return None


def extract_improvement_meshes(
    game_data: Path | None = None,
    output_dir: Path | None = None,
    *,
    verbose: bool = True,
) -> dict[str, int]:
    """
    Extract 3D improvement (building) meshes and render them to 2D images.

    Runs after unit-mesh extraction. Output files are named
    IMPROVEMENT_3D_{name}.png in extracted/sprites/improvements/, where
    they classify into the existing 'improvements' category alongside the
    2D improvement icons.

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

    if game_data is None:
        game_data = find_game_data()
    if game_data is None or not game_data.exists():
        raise FileNotFoundError("Could not find Old World game data!")

    if output_dir is None:
        output_dir = Path.cwd() / "extracted"

    sprites_dir = output_dir / "sprites" / "improvements"
    sprites_dir.mkdir(parents=True, exist_ok=True)

    if verbose:
        print("\n" + "=" * 60)
        print("3D Improvement Mesh Extraction")
        print("=" * 60)

    exclude_pattern = load_exclusion_pattern()
    excluded_count = 0

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

        texture_lookup = build_texture_lookup(env)

        if verbose:
            print(f"Found {len(mesh_lookup)} meshes, {len(texture_lookup)} diffuse textures")
            if unreadable:
                print(f"Skipped {unreadable} unreadable objects")
            print(f"Processing {len(IMPROVEMENT_MESHES)} improvement meshes...\n")

        rendered = 0
        skipped = 0

        from pinacotheca.prefab import (
            bake_to_obj,
            drop_splat_meshes,
            find_diffuse_for_prefab,
            find_root_gameobject,
            strip_plinth_from_obj,
            walk_prefab,
        )

        for mesh_name, output_name in IMPROVEMENT_MESHES:
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

            # Prefer the prefab walker so we apply the building's authored
            # root rotation/scale (most building meshes are laid flat in
            # mesh space and only stand up correctly via the prefab's TRS).
            prefab_base = re.sub(r"_LOD\d+$", "", mesh_name, flags=re.IGNORECASE)
            root_go = find_root_gameobject(env, prefab_base)
            rendered_via_prefab = False
            if root_go is not None:
                parts = walk_prefab(root_go)
                # Drop lower-LOD duplicates first (we render LOD0 only).
                lod_kept: list[Any] = []
                for p in parts:
                    try:
                        m = p.mesh_obj.deref_parse_as_object()
                        n = getattr(m, "m_Name", "")
                    except Exception:
                        continue
                    if not n:
                        continue
                    if re.search(r"_LOD[12]$", n, flags=re.IGNORECASE):
                        continue
                    lod_kept.append(p)
                # Then drop splat-shader meshes (heightmaps, alphamaps,
                # water surfaces) by material name — catches custom-named
                # offenders like Quad/MarketSplat/HamletFloor that the
                # previous mesh-name-only filter missed.
                kept = drop_splat_meshes(lod_kept)
                if kept:
                    obj_str = bake_to_obj(kept)
                    obj_str = strip_plinth_from_obj(obj_str)
                    tex_img = find_diffuse_for_prefab(kept) or None
                    # Fall back to the lookup-table texture if the prefab's
                    # materials don't expose one we can read.
                    if tex_img is None:
                        tex_obj_fallback = _find_texture(texture_lookup, mesh_name, output_name)
                        if tex_obj_fallback is not None:
                            try:
                                tex_img = tex_obj_fallback.read().image
                            except Exception:
                                tex_img = None
                    if obj_str and tex_img is not None:
                        try:
                            img = render_mesh_to_image(obj_str, tex_img, force_upright=True)
                            img.save(out_path, optimize=False)
                            rendered += 1
                            rendered_via_prefab = True
                            if verbose:
                                print(f"  [OK] {output_name} (prefab, {len(kept)} parts)")
                            del img
                            del tex_img
                            gc.collect()
                        except Exception as e:
                            if verbose:
                                print(f"  [WARN] {output_name} prefab render failed: {e}")

            if rendered_via_prefab:
                continue

            # Fallback: render the raw mesh asset (no prefab transform).
            resolved = _resolve_mesh_variant(mesh_lookup, mesh_name)
            if resolved is None:
                if verbose:
                    print(f"  [SKIP] {output_name} - mesh not found ({mesh_name})")
                skipped += 1
                continue

            texture_obj = _find_texture(texture_lookup, mesh_name, output_name)
            if texture_obj is None:
                if verbose:
                    print(f"  [SKIP] {output_name} - texture not found")
                skipped += 1
                continue

            try:
                mesh_data = mesh_lookup[resolved].read()
                obj_data = mesh_data.export()
                tex_data = texture_obj.read()
                texture_image = tex_data.image

                if obj_data and texture_image:
                    obj_data = strip_plinth_from_obj(obj_data)
                    img = render_mesh_to_image(obj_data, texture_image, force_upright=True)
                    img.save(out_path, optimize=False)
                    rendered += 1
                    if verbose:
                        print(f"  [OK] {output_name} (raw mesh)")

                    del img
                    del texture_image

                gc.collect()

            except Exception as e:
                if verbose:
                    print(f"  [ERROR] {output_name} - {e}")
                skipped += 1

        if verbose:
            print("\n" + "=" * 60)
            print("3D IMPROVEMENT EXTRACTION COMPLETE")
            print("=" * 60)
            print(f"Rendered: {rendered}")
            if excluded_count > 0:
                print(f"Excluded by pattern: {excluded_count}")
            print(f"Skipped: {skipped}")
            print(f"Output: {sprites_dir}")

        return {"rendered": rendered, "skipped": skipped, "excluded": excluded_count}

    finally:
        os.chdir(original_cwd)


# Curated list of composite (multi-piece prefab) buildings.
# Format: (root_gameobject_name, output_name)
# These buildings are stored as Unity prefab trees rather than single
# combined meshes. Rendered via the prefab walker in `prefab.py`.
COMPOSITE_PREFABS: list[tuple[str, str]] = [
    # Empires of the Indus DLC capitals
    ("Maurya_Capital", "MAURYA_CAPITAL"),
    ("Tamil_Capital", "TAMIL_CAPITAL"),
    ("Yuezhi_Capital", "YUEZHI_CAPITAL"),
    # Aksum capital
    ("AksumCapitol", "AKSUM_CAPITAL"),
    # Wonders / landmarks
    ("Hanging_Garden", "HANGING_GARDEN"),
    ("Kushite_Pyramid", "KUSHITE_PYRAMID"),
    ("Ishtar_Gate33", "ISHTAR_GATE"),
    ("Pyramid_lvl_1", "PYRAMID_LVL_1"),
    ("Pyramid_lvl_2", "PYRAMID_LVL_2"),
    ("Pyramid_lvl_3", "PYRAMID_LVL_3"),
    ("Pyramid_lvl_4", "PYRAMID_LVL_4"),
]


def extract_composite_meshes(
    game_data: Path | None = None,
    output_dir: Path | None = None,
    *,
    verbose: bool = True,
) -> dict[str, int]:
    """
    Extract composite prefab buildings (multi-piece structures).

    Walks each prefab's GameObject/Transform hierarchy, bakes per-leaf
    world matrices into vertex positions, and renders the combined OBJ
    via the existing renderer pipeline. Falls back gracefully when a
    curated entry turns out to be a regular single mesh.

    Output: extracted/sprites/improvements/IMPROVEMENT_3D_<NAME>.png
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
        return {"rendered": 0, "skipped": 0, "excluded": 0}

    from pinacotheca.prefab import (
        bake_to_obj,
        drop_splat_meshes,
        find_diffuse_for_prefab,
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

    if verbose:
        print("\n" + "=" * 60)
        print("3D Composite Prefab Extraction")
        print("=" * 60)

    exclude_pattern = load_exclusion_pattern()
    excluded_count = 0

    original_cwd = os.getcwd()
    os.chdir(str(game_data))

    try:
        if verbose:
            print("Loading assets...")

        env = UnityPy.Environment()
        env.load_file(str(game_data / "resources.assets"))

        if verbose:
            print(f"Processing {len(COMPOSITE_PREFABS)} composite prefabs...\n")

        rendered = 0
        skipped = 0

        for root_name, output_name in COMPOSITE_PREFABS:
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

            root_go = find_root_gameobject(env, root_name)
            if root_go is None:
                if verbose:
                    print(f"  [SKIP] {output_name} - no GameObject named '{root_name}'")
                skipped += 1
                continue

            parts = walk_prefab(root_go)
            # Drop splat-shader meshes (heightmap/alphamap/water surfaces).
            # Composite prefabs ship a courtyard floor + heightmap + clutter
            # mask alongside the actual building geometry; rendering the
            # splat planes with a standard shader produces alphamap "floor"
            # artifacts under the building.
            parts = drop_splat_meshes(parts)
            if not parts:
                if verbose:
                    print(
                        f"  [SKIP] {output_name} - prefab has no MeshFilter leaves "
                        "(likely a combined mesh)"
                    )
                skipped += 1
                continue

            try:
                obj_str = bake_to_obj(parts)
                obj_str = strip_plinth_from_obj(obj_str)
                texture_image = find_diffuse_for_prefab(parts)

                if not obj_str:
                    if verbose:
                        print(f"  [SKIP] {output_name} - empty bake output")
                    skipped += 1
                    continue
                if texture_image is None:
                    if verbose:
                        print(f"  [SKIP] {output_name} - no diffuse texture found")
                    skipped += 1
                    continue

                img = render_mesh_to_image(obj_str, texture_image, force_upright=True)
                img.save(out_path, optimize=False)
                rendered += 1
                if verbose:
                    print(f"  [OK] {output_name} ({len(parts)} parts)")

                del img
                del texture_image
                gc.collect()

            except Exception as e:
                if verbose:
                    print(f"  [ERROR] {output_name} - {e}")
                skipped += 1

        if verbose:
            print("\n" + "=" * 60)
            print("3D COMPOSITE EXTRACTION COMPLETE")
            print("=" * 60)
            print(f"Rendered: {rendered}")
            if excluded_count > 0:
                print(f"Excluded by pattern: {excluded_count}")
            print(f"Skipped: {skipped}")
            print(f"Output: {sprites_dir}")

        return {"rendered": rendered, "skipped": skipped, "excluded": excluded_count}

    finally:
        os.chdir(original_cwd)
