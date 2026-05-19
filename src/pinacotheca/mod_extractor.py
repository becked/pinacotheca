"""
Asset extraction for installed Old World mods.

Mods discovered by :mod:`pinacotheca.mod_scanner` are extracted into
``extracted/sprites/mods/<slug>/<category>/<filename>.png``. 3D bundles
go through the same prefab walker + render pipeline as the base game's
improvement/unit extraction; 2D bundles iterate ``Sprite`` objects and
save them directly.

Naming for 3D outputs follows the mod's own ``Infos/asset-*-add.xml``
mapping when present (each ``<zType>ASSET_<X></zType>`` becomes
``<X>_3D.png`` minus the asset-category prefix), so a consumer reading
the gallery picks up the same conventional names the mod author used in
their XML. When no asset XML maps to a prefab, the bundle's GameObject
name is used as a fallback.

Each mod writes a ``mod.json`` sidecar at the mod's output root with
display name, author, version, description, and a resolved
``attribution`` table. The web gallery's manifest builder reads these
to stamp per-sprite ``authors`` and surface bylines.

Publication approval
--------------------
:data:`APPROVED_AUTHORS` is an allowlist of creators who have granted
explicit approval for their work to appear in the deployed pinacotheca
gallery. A mod sprite ships only when **every** credited author is in
the set; sprites with no resolved authors are filtered too (no
approval). Extraction still writes every mod file to disk locally
(so a user with the mod installed can use the output for per-ankh or
other tools), but :func:`compute_excluded_mod_globs` returns the
file-path globs the gallery-filter mechanism uses to keep
unapproved files out of the deployed manifest and the gh-pages bundle.

When an author grants approval, add their name to
``APPROVED_AUTHORS`` and rerun ``pinacotheca-mods``; the gallery
filter sidecar gets rewritten automatically and the gallery's Mods
section updates on the next manifest build.
"""

from __future__ import annotations

import gc
import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Per-mod attribution overrides. The mod's ``<author>`` field gives us the
# primary credit, but mods routinely bundle work from collaborators that
# ModInfo doesn't expose as structured data — sometimes mentioned in the
# free-text description (Dynamic Unit thanks "And" for icons; NSG credits
# the same in its Credits block), sometimes communicated out-of-band
# (Maniac's Greek Dynasties mod ships the NSG mesh set without crediting
# it inline). Free-text parsing is brittle, so we keep this table
# explicit. Each entry is ``{"default": [authors], "overrides":
# [{"pattern": regex, "authors": [authors]}]}``. ``default`` falls back
# to ``[mod.author]`` when omitted; ``overrides`` are evaluated against
# each sprite's basename (no extension) in order, first match wins.
_MOD_ATTRIBUTION: dict[str, dict[str, Any]] = {
    "dynamic-unit": {
        # "thanks to And" for icons, per the mod description.
        "default": ["Harry", "And"],
    },
    "nation-specific-graphics-units": {
        # Per the description's Credits block: "And (Research), Harry (C# DLL
        # Modding), Shirotora Kenshin (3D Artwork, XML)". Mohawk Games is
        # credited too but it's the game studio, not a contributor.
        "default": ["Shirotora Kenshin", "And", "Harry"],
    },
    "the-greek-dynasties": {
        # Maniac is the mod author; the 3D unit meshes are NSG's
        # (communicated by the user out-of-band), and the resource
        # icons are Revan's per the description: "I used the icons
        # provided in the Resources+ mod by Revan".
        "default": ["Maniac"],
        "overrides": [
            {"pattern": r"^UNIT_3D_", "authors": ["Maniac", "Shirotora Kenshin"]},
            {"pattern": r"^RESOURCE_", "authors": ["Maniac", "Revan"]},
        ],
    },
}


def _resolved_attribution(slug: str, primary_author: str) -> dict[str, Any]:
    """Return ``{"default": [...], "overrides": [...]}`` for a mod slug.

    Falls back to ``{"default": [primary_author]}`` (or an empty default
    when the ModInfo author field is blank) for mods not in the override
    table. The dict shape mirrors what gets written into ``mod.json`` so
    the TS-side manifest generator can apply per-sprite overrides without
    re-parsing the source.
    """
    entry = _MOD_ATTRIBUTION.get(slug)
    if entry is None:
        return {"default": [primary_author] if primary_author else [], "overrides": []}
    default = entry.get("default")
    if default is None:
        default = [primary_author] if primary_author else []
    overrides = entry.get("overrides", [])
    return {"default": default, "overrides": overrides}


# Mod creators who have explicitly approved publication of their work
# in the deployed pinacotheca gallery. A sprite ships only when ALL of
# its credited authors are in this set; sprites with no resolved
# authors are filtered out as well (no approval). Files still get
# rendered locally so the user can consume them via per-ankh or
# Finder; only the gallery manifest + gh-pages deploy filter them
# out. See the module docstring for the policy rationale.
#
# To add an author: confirm explicit approval, then append their name
# here and rerun `pinacotheca-mods` (or any command that writes the
# gallery-filter sidecar).
APPROVED_AUTHORS: frozenset[str] = frozenset(
    {
        "Dale Kent",  # Byzantine Empire mod
        "Harry",  # Dynamic Unit mod
        "And",  # Co-credited on Dynamic Unit icons and NSG; approval
        #              given via Discord with the condition that he be
        #              credited on every published image (already
        #              handled via _MOD_ATTRIBUTION).
    }
)


def _resolve_authors_for_sprite(
    sprite_name: str, attribution: dict[str, Any] | None, fallback_author: str
) -> list[str]:
    """Python mirror of the TS-side ``resolveAuthors``. Picks the first
    pattern match from ``attribution.overrides``; falls back to
    ``attribution.default``, then to ``[fallback_author]``.
    """
    if attribution is None:
        return [fallback_author] if fallback_author else []
    for override in attribution.get("overrides", []) or []:
        try:
            if re.search(override["pattern"], sprite_name):
                return list(override["authors"])
        except re.error:
            continue
    default = attribution.get("default")
    if default:
        return list(default)
    return [fallback_author] if fallback_author else []


def compute_excluded_mod_globs(output_dir: Path) -> list[str]:
    """Walk every extracted mod and return file-path globs (relative to
    ``extracted/sprites/``) for sprites that are NOT cleared by
    :data:`APPROVED_AUTHORS`.

    A sprite is filtered when any of:
      - It has no resolved authors (we have no one to ask for approval).
      - At least one of its authors is missing from
        :data:`APPROVED_AUTHORS`.

    Emits one literal-path glob per matching ``.png`` plus a parallel
    glob for the ``.json`` render-metadata sidecar that lives next to
    each 3D render. Literal paths trivially satisfy the gallery
    filter's ``*``-only contract (no wildcard characters in our
    filenames) and let the same mechanism that excludes urban
    composites from deploy also filter these.
    """
    mods_root = output_dir / "sprites" / "mods"
    if not mods_root.is_dir():
        return []

    globs: set[str] = set()
    for mod_dir in sorted(mods_root.iterdir()):
        if not mod_dir.is_dir():
            continue
        sidecar = mod_dir / "mod.json"
        if not sidecar.exists():
            continue
        try:
            mod_info = json.loads(sidecar.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        attribution = mod_info.get("attribution")
        fallback = mod_info.get("author", "")
        for sub_dir in sorted(mod_dir.iterdir()):
            if not sub_dir.is_dir():
                continue
            for png_path in sorted(sub_dir.glob("*.png")):
                authors = _resolve_authors_for_sprite(png_path.stem, attribution, fallback)
                # Ship only when every credited author is in the
                # approved set AND we have at least one author. Empty
                # author lists fail (no approval to publish).
                if authors and set(authors).issubset(APPROVED_AUTHORS):
                    continue
                rel = f"mods/{mod_dir.name}/{sub_dir.name}/{png_path.name}"
                globs.add(rel)
                # Also exclude the matching render-metadata sidecar
                # (3D renders only — 2D extracts have no sidecar but
                # adding the glob is harmless when the file is absent).
                globs.add(rel[:-4] + ".json")
    return sorted(globs)


# Map an `ASSET_<CATEGORY>_<NAME>` prefix to a (sprite subdirectory,
# 3D filename prefix) pair. Mirrors the layout used by the base-game
# extractor so per-ankh and the SvelteKit gallery can route mod assets
# through the same conventions.
_ASSET_PREFIX_ROUTES: tuple[tuple[str, str, str], ...] = (
    ("ASSET_UNIT_", "units", "UNIT_3D_"),
    ("ASSET_IMPROVEMENT_", "improvements", "IMPROVEMENT_3D_"),
    ("ASSET_RESOURCE_", "resources", "RESOURCE_3D_"),
)


def _route_for_asset(asset_type: str) -> tuple[str, str, str] | None:
    """Return ``(category_dir, filename_prefix, stripped_name)`` for an
    ``ASSET_<CATEGORY>_<NAME>`` zType, or ``None`` when the prefix isn't
    one we recognize.
    """
    for prefix, category, fname_prefix in _ASSET_PREFIX_ROUTES:
        if asset_type.startswith(prefix):
            return category, fname_prefix, asset_type[len(prefix) :]
    return None


def _parse_mod_asset_xml(mod_dir: Path) -> list[tuple[str, str]]:
    """Walk a mod's ``Infos/`` directory for any ``asset*.xml`` and
    extract every ``(zType, zAsset)`` pair. Mod conventions vary —
    "Nation Specific Graphics - Units" ships per-nation XML files
    (``asset-greece-units-add.xml`` etc.); "Dynamic Unit" puts everything
    in a single ``asset-add.xml``. Both shapes flatten to the same
    pair list here.

    Returns an empty list when the mod ships no asset XML.
    """
    infos_dir = mod_dir / "Infos"
    if not infos_dir.is_dir():
        return []
    pairs: list[tuple[str, str]] = []
    for xml_path in sorted(infos_dir.glob("asset*.xml")):
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
        except ET.ParseError as exc:
            logger.warning("Failed to parse %s: %s", xml_path, exc)
            continue
        for entry in root.findall("Entry"):
            ztype_el = entry.find("zType")
            zasset_el = entry.find("zAsset")
            if ztype_el is None or zasset_el is None:
                continue
            ztype = (ztype_el.text or "").strip()
            zasset = (zasset_el.text or "").strip()
            if ztype and zasset:
                pairs.append((ztype, zasset))
    return pairs


@dataclass
class ModRenderJob:
    """One 3D render job for a mod: a prefab root name plus output target.

    ``bundle_name`` is the first path segment of the mod's declared
    ``zAsset`` value (e.g. ``custom_units`` for
    ``custom_units/Units/Military/Greece/...``). The extractor uses
    this to route the job to the correct bundle so we don't emit
    spurious 'prefab not found' warnings when iterating bundles a job
    doesn't belong to. When ``zAsset`` has only one path component the
    field is the empty string (legacy-base-game references like
    ``Prefabs/Resource/Iron`` skip 3D rendering entirely since the
    target lives outside the mod's bundles).
    """

    asset_type: str  # e.g. "ASSET_UNIT_GREECE_ELITE_SWORDSMAN"
    prefab_name: str  # e.g. "Greece_Elite_Swordsman"
    category: str  # sprite subdir name (e.g. "units")
    output_basename: str  # e.g. "UNIT_3D_GREECE_ELITE_SWORDSMAN"
    bundle_name: str  # leading path segment of the mod's zAsset reference


def _build_render_jobs(mod_dir: Path, bundle_names: set[str]) -> list[ModRenderJob]:
    """Build the list of 3D render jobs from a mod's asset XML.

    Pairs whose ``zType`` doesn't begin with one of the known
    ``ASSET_<CATEGORY>_`` prefixes are skipped — mods occasionally
    define ``ASSET_SPRITE_SHEET_*`` entries (2D content) that the
    sprite-extraction path covers separately.

    Jobs whose ``zAsset`` references a path outside any of the mod's
    own bundles are also dropped. Greek Dynasties for instance points
    several ``ASSET_RESOURCE_*`` entries at base-game prefab paths
    like ``Prefabs/Resource/Iron`` — those targets live in the game
    install, not in the mod bundle, so we have nothing to render.
    """
    jobs: list[ModRenderJob] = []
    for ztype, zasset in _parse_mod_asset_xml(mod_dir):
        route = _route_for_asset(ztype)
        if route is None:
            continue
        category, fname_prefix, stripped = route
        parts = zasset.split("/")
        if len(parts) < 2:
            continue
        bundle_name = parts[0]
        if bundle_name not in bundle_names:
            continue
        prefab = parts[-1]
        if not prefab:
            continue
        jobs.append(
            ModRenderJob(
                asset_type=ztype,
                prefab_name=prefab,
                category=category,
                output_basename=f"{fname_prefix}{stripped}",
                bundle_name=bundle_name,
            )
        )
    return jobs


def _write_mod_sidecar(mod_root: Path, mod: Any) -> None:
    """Write the per-mod ``mod.json`` describing display name, author,
    version, description, attribution table, and the extraction
    timestamp. The web manifest builder reads this to surface subtle
    attribution next to each mod's sprite grid AND on individual
    sprites (search results / lightbox).
    """
    attribution = _resolved_attribution(mod.slug, mod.author)
    payload = {
        "slug": mod.slug,
        "displayName": mod.display_name,
        "author": mod.author,
        "version": mod.version,
        "description": mod.description,
        "attribution": attribution,
        "extractedAt": datetime.now(UTC).isoformat(),
    }
    mod_root.mkdir(parents=True, exist_ok=True)
    sidecar = mod_root / "mod.json"
    sidecar.write_text(json.dumps(payload, indent=2) + "\n")


def _extract_2d_bundle(
    bundle_path: Path,
    out_dir: Path,
    *,
    verbose: bool,
) -> int:
    """Save every readable image from a 2D mod bundle as a PNG into
    ``out_dir``. Returns the count saved.

    Prefers ``Sprite`` objects (which carry the atlas-crop metadata mod
    authors typically attach), but falls back to the Texture2D when the
    sprite's cropped image is empty. Greek Dynasties' resource bundle
    is the canonical example — its sprite metadata triggers a
    UnityPy crop bug that returns blank pixels, while the underlying
    1:1 textures decode cleanly.

    Texture2Ds with no matching Sprite are emitted directly under their
    own ``m_Name``. Existing files are skipped (idempotent).
    """
    import UnityPy
    from PIL import Image

    env = UnityPy.load(str(bundle_path))
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = 0

    def _image_has_content(img: Image.Image | None) -> bool:
        if img is None:
            return False
        # An "empty" sprite image is fully transparent or fully zero-RGB.
        # Bbox returns None when every pixel's alpha is 0.
        rgba = img.convert("RGBA")
        return rgba.getbbox() is not None

    # Index Texture2Ds by name so we can fall back when a Sprite's cropped
    # image is empty. Sprites consumed by name; remaining Texture2Ds emit
    # standalone after the sprite pass.
    textures_by_name: dict[str, Any] = {}
    for obj in env.objects:
        if obj.type.name != "Texture2D":
            continue
        try:
            tex_data = obj.read()
            tex_name = getattr(tex_data, "m_Name", "")
            if tex_name and tex_name not in textures_by_name:
                textures_by_name[tex_name] = tex_data
        except Exception:
            continue

    consumed_textures: set[str] = set()
    for obj in env.objects:
        if obj.type.name != "Sprite":
            continue
        try:
            data = obj.read()
            name = getattr(data, "m_Name", "")
            if not name:
                continue
            out_path = out_dir / f"{name}.png"
            if out_path.exists():
                consumed_textures.add(name)
                continue
            img = data.image
            if not _image_has_content(img):
                # Sprite crop produced an empty image; try the matching
                # Texture2D directly. Mod authors often ship 1:1
                # sprite/texture pairs, so the underlying texture has
                # the data we want.
                tex = textures_by_name.get(name)
                if tex is not None:
                    try:
                        tex_img = tex.image
                        if _image_has_content(tex_img):
                            img = tex_img
                    except Exception:
                        pass
            if not _image_has_content(img):
                continue
            img.save(out_path)
            consumed_textures.add(name)
            saved += 1
            del img
            del data
        except Exception as exc:
            if verbose:
                print(f"  [WARN] sprite extract failed in {bundle_path.name}: {exc}")

    # Any Texture2D not exposed as a Sprite still gets emitted — this is
    # how Byzantine Empire's bundle ships its assets (Texture2D + matching
    # Sprite, but some sprite metadata is incomplete in mod toolchains).
    for tex_name, tex in textures_by_name.items():
        if tex_name in consumed_textures:
            continue
        out_path = out_dir / f"{tex_name}.png"
        if out_path.exists():
            continue
        try:
            img = tex.image
        except Exception:
            continue
        if not _image_has_content(img):
            continue
        img.save(out_path)
        saved += 1

    gc.collect()
    return saved


# Default (filename suffix, pre-rotation degrees) pair per 3D mod
# prefab. ``_FRONT`` defaults to the 180° pre-rotation that points
# Unity-authored -Z meshes at our +Z camera; ``_BACK`` is the inverse.
# Mod authors don't agree on a canonical facing direction though, so
# meshes authored facing +Z come out reversed under the default. The
# per-prefab override set below flips the mapping for those.
_DEFAULT_FRONT_DEG: float = 180.0
_DEFAULT_BACK_DEG: float = 0.0

# Prefab GameObject names whose authored facing is +Z (the reverse of
# the base-game convention). For these, ``_FRONT.png`` must be rendered
# at 0° and ``_BACK.png`` at 180° so the gallery's FRONT/BACK suffixes
# correspond to the soldier's actual front/back. List captured by
# eyeballing the renders — Shirotora Kenshin's Nation Specific Graphics -
# Units mod authored its swordsmen inconsistently across nations.
_BACK_AUTHORED_PREFABS: frozenset[str] = frozenset(
    {
        "Assyria_Elite_Swordsman",
        "Babylonia_Elite_Swordsman",
        "Carthage_Elite_Swordsman",
        "Egypt_Elite_Swordsman",
        "Persia_Elite_Swordsman",
        "Rome_Elite_Swordsman",
    }
)


def _views_for_prefab(prefab_name: str) -> tuple[tuple[str, float], ...]:
    """Return the (suffix, degrees) views to render for one prefab.
    Flips the default FRONT/BACK rotation mapping for prefabs the mod
    author authored facing +Z so the suffix always reflects the
    soldier's actual front/back, not the rotation amount.
    """
    if prefab_name in _BACK_AUTHORED_PREFABS:
        return (("_FRONT", _DEFAULT_BACK_DEG), ("_BACK", _DEFAULT_FRONT_DEG))
    return (("_FRONT", _DEFAULT_FRONT_DEG), ("_BACK", _DEFAULT_BACK_DEG))


def _render_mod_prefab_view(
    kept: list[Any],
    pre_rotation_y_deg: float,
    out_path: Path,
    *,
    verbose: bool,
    label: str,
) -> bool:
    """Render one orientation of a mod prefab to ``out_path``. Returns
    True on success, False on any expected-failure path (no texture,
    empty bake, etc.). Exceptions during the OpenGL render are caught
    and surfaced via ``verbose`` so a failure in one orientation
    doesn't kill the whole bundle.
    """
    from pinacotheca.prefab import (
        bake_to_obj,
        find_diffuse_for_prefab,
        find_normal_map_for_prefab,
    )
    from pinacotheca.render_metadata import write_sidecar
    from pinacotheca.renderer import render_mesh_to_image

    obj_str = bake_to_obj(kept, pre_rotation_y_deg=pre_rotation_y_deg)
    if not obj_str:
        if verbose:
            print(f"  [SKIP]   {label} - empty bake")
        return False
    tex_img = find_diffuse_for_prefab(kept)
    if tex_img is None:
        if verbose:
            print(f"  [SKIP]   {label} - no diffuse texture")
        return False
    normal_map = find_normal_map_for_prefab(kept)
    try:
        img, meta = render_mesh_to_image(
            obj_str,
            tex_img,
            force_upright=False,
            normal_map_image=normal_map,
        )
        img.save(out_path, optimize=False)
        write_sidecar(out_path, meta)
        del img
        del tex_img
        gc.collect()
        return True
    except Exception as exc:
        if verbose:
            print(f"  [ERROR]  {label} - render failed: {exc}")
        return False


def _extract_3d_jobs(
    bundle_path: Path,
    mod_root: Path,
    jobs: list[ModRenderJob],
    *,
    verbose: bool,
) -> tuple[int, int]:
    """Render the 3D jobs whose prefabs live in this bundle. Returns
    ``(rendered, skipped)`` — counts are per (prefab, view) pair, so a
    prefab that successfully renders both FRONT and BACK contributes 2
    to ``rendered``.

    Routes each prefab through the same walker + renderer the base-game
    improvement extractor uses, with two adaptations: (1) the prefab
    walker has SkinnedMeshRenderer leaf support already (needed for
    rigged unit meshes); (2) packed-PBR is skipped — mod URP materials
    lack the HDRP packed map our base-game renderer samples for
    occlusion modulation, and `_MetallicGlossMap` has no occlusion
    channel to substitute.
    """
    import UnityPy

    from pinacotheca.prefab import (
        drop_splat_meshes,
        find_root_gameobject,
        walk_prefab,
    )

    env = UnityPy.load(str(bundle_path))
    rendered = 0
    skipped = 0
    for job in jobs:
        out_dir = mod_root / job.category
        out_dir.mkdir(parents=True, exist_ok=True)
        view_targets = [
            (suffix, deg, out_dir / f"{job.output_basename}{suffix}.png")
            for suffix, deg in _views_for_prefab(job.prefab_name)
        ]
        if all(p.exists() for _, _, p in view_targets):
            if verbose:
                print(f"  [EXISTS] {job.output_basename} (all views)")
            continue
        root_go = find_root_gameobject(env, job.prefab_name)
        if root_go is None:
            if verbose:
                print(
                    f"  [SKIP]   {job.output_basename} - prefab '{job.prefab_name}' not in bundle"
                )
            skipped += len(view_targets)
            continue
        try:
            parts = walk_prefab(root_go, drop_animated_smr_rotation=False)
        except Exception as exc:
            if verbose:
                print(f"  [SKIP]   {job.output_basename} - walk failed: {exc}")
            skipped += len(view_targets)
            continue
        kept = drop_splat_meshes(parts)
        if not kept:
            if verbose:
                print(f"  [SKIP]   {job.output_basename} - no usable meshes")
            skipped += len(view_targets)
            continue
        for suffix, deg, out_path in view_targets:
            if out_path.exists():
                continue
            label = f"{job.output_basename}{suffix}"
            if _render_mod_prefab_view(kept, deg, out_path, verbose=verbose, label=label):
                rendered += 1
                if verbose:
                    print(f"  [OK]     {label} ({len(kept)} parts)")
            else:
                skipped += 1
    return rendered, skipped


def _extract_fallback_3d(
    bundle_path: Path,
    mod_root: Path,
    *,
    verbose: bool,
) -> tuple[int, int]:
    """Render every parent-less prefab in a 3D bundle when the mod ships
    no asset XML to identify which GameObjects are renderable roots.

    Filters to GameObjects whose Transform has no parent AND that own (or
    descend to) a MeshFilter or SkinnedMeshRenderer; deduplicates by name
    (UnityPy can yield the same root from multiple file slots). Outputs
    land under ``mod_root/units/UNIT_3D_<NAME>.png`` since the only
    fallback case so far is unit content; we can extend categorization
    later if a mod ships a different prefab type without asset XML.
    """
    import UnityPy

    from pinacotheca.prefab import (
        drop_splat_meshes,
        find_root_gameobject,
        walk_prefab,
    )

    env = UnityPy.load(str(bundle_path))
    candidate_names: set[str] = set()
    for obj in env.objects:
        if obj.type.name != "GameObject":
            continue
        try:
            name = obj.peek_name()
        except Exception:
            continue
        if not name or name in candidate_names:
            continue
        candidate_names.add(name)

    out_dir = mod_root / "units"
    rendered = 0
    skipped = 0
    seen_outputs: set[str] = set()
    for name in sorted(candidate_names):
        if "_geo" in name.lower():
            continue  # leaf mesh GameObject under a prefab root; the root carries it
        output_basename = f"UNIT_3D_{_to_screaming_snake(name)}"
        if output_basename in seen_outputs:
            continue
        view_targets = [
            (suffix, deg, out_dir / f"{output_basename}{suffix}.png")
            for suffix, deg in _views_for_prefab(name)
        ]
        if all(p.exists() for _, _, p in view_targets):
            seen_outputs.add(output_basename)
            continue
        root_go = find_root_gameobject(env, name)
        if root_go is None:
            continue
        try:
            parts = walk_prefab(root_go, drop_animated_smr_rotation=False)
        except Exception:
            continue
        kept = drop_splat_meshes(parts)
        if not kept:
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        for suffix, deg, out_path in view_targets:
            if out_path.exists():
                continue
            label = f"{output_basename}{suffix} (fallback)"
            if _render_mod_prefab_view(kept, deg, out_path, verbose=verbose, label=label):
                rendered += 1
                seen_outputs.add(output_basename)
                if verbose:
                    print(f"  [OK]     {label}")
            else:
                skipped += 1
    return rendered, skipped


_SCREAMING_RE = re.compile(r"[^A-Za-z0-9]+")


def _to_screaming_snake(name: str) -> str:
    """Turn a mixed-case GameObject name into ``SCREAMING_SNAKE_CASE``
    for use as the canonical output filename suffix.
    """
    out = _SCREAMING_RE.sub("_", name).strip("_").upper()
    return out or "UNNAMED"


def extract_mod_assets(
    output_dir: Path | None = None,
    *,
    mods_dir: Path | None = None,
    verbose: bool = True,
) -> dict[str, dict[str, int]]:
    """Discover installed mods and extract their visual assets.

    For each mod with at least one extractable bundle:
      - 3D bundles: render each prefab root referenced by the mod's
        asset XML (or fall back to bundle scanning) into
        ``extracted/sprites/mods/<slug>/<category>/<NAME>.png``.
      - 2D bundles: save each ``Sprite`` into
        ``extracted/sprites/mods/<slug>/sprites/<NAME>.png``.
      - Write ``extracted/sprites/mods/<slug>/mod.json`` with
        attribution and timestamp.

    Args:
        output_dir: Output root (defaults to ``./extracted``).
        mods_dir: Override the auto-detected mods directory.
        verbose: Print progress.

    Returns:
        Per-mod result dict: ``{slug: {"rendered": N, "skipped": N,
        "sprites": N}}``. Empty when no mods directory was found.
    """
    from pinacotheca.mod_scanner import discover_mods

    if output_dir is None:
        output_dir = Path.cwd() / "extracted"

    mods_root = output_dir / "sprites" / "mods"
    mods = discover_mods(mods_dir)
    mods = [m for m in mods if m.has_extractable_content]

    if verbose:
        print("\n" + "=" * 60)
        print("Mod Asset Extraction")
        print("=" * 60)
        if not mods:
            print("No mods with extractable content found.")
            return {}
        print(f"Discovered {len(mods)} extractable mod(s)")

    results: dict[str, dict[str, int]] = {}
    for mod in mods:
        if verbose:
            print(f"\n[{mod.display_name}] by {mod.author or '?'} (v{mod.version or '?'})")
        mod_root = mods_root / mod.slug
        _write_mod_sidecar(mod_root, mod)
        result = {"rendered": 0, "skipped": 0, "sprites": 0}

        threed_bundles = [b for b in mod.bundles if b.has_3d_content]
        twod_bundles = [b for b in mod.bundles if b.has_2d_content]
        threed_bundle_names = {Path(b.name).stem for b in threed_bundles}
        jobs = _build_render_jobs(mod.mod_dir, threed_bundle_names)

        if threed_bundles and jobs:
            for bundle in threed_bundles:
                bundle_jobs = [j for j in jobs if j.bundle_name == Path(bundle.name).stem]
                if not bundle_jobs:
                    continue
                if verbose:
                    print(f"  Rendering 3D bundle '{bundle.name}' (Unity {bundle.unity_version})")
                r, s = _extract_3d_jobs(bundle.path, mod_root, bundle_jobs, verbose=verbose)
                result["rendered"] += r
                result["skipped"] += s
        elif threed_bundles:
            # 3D content but no asset XML mapping — fall back to bundle scan.
            for bundle in threed_bundles:
                if verbose:
                    print(f"  Rendering 3D bundle '{bundle.name}' (fallback discovery)")
                r, s = _extract_fallback_3d(bundle.path, mod_root, verbose=verbose)
                result["rendered"] += r
                result["skipped"] += s

        for bundle in twod_bundles:
            sprites_out = mod_root / "sprites"
            if verbose:
                print(f"  Extracting 2D bundle '{bundle.name}'")
            n = _extract_2d_bundle(bundle.path, sprites_out, verbose=verbose)
            result["sprites"] += n

        results[mod.slug] = result
        if verbose:
            print(
                f"  → rendered={result['rendered']} skipped={result['skipped']} "
                f"sprites={result['sprites']}"
            )

    if verbose:
        print("\n" + "=" * 60)
        print("MOD EXTRACTION COMPLETE")
        print("=" * 60)
        total_rendered = sum(r["rendered"] for r in results.values())
        total_sprites = sum(r["sprites"] for r in results.values())
        total_skipped = sum(r["skipped"] for r in results.values())
        print(
            f"3D renders: {total_rendered}  2D sprites: {total_sprites}  Skipped: {total_skipped}"
        )
        print(f"Output: {mods_root}")

    return results
