"""
Mod discovery for Old World's mod directory.

Reads ``~/Library/Application Support/OldWorld/Mods/`` (macOS) or
``%USERPROFILE%\\Documents\\My Games\\OldWorld\\Mods\\`` (Windows), parses
each mod's ``ModInfo.xml``, and classifies each Unity AssetBundle in the
mod's ``Assets/`` directory by content type. The classifier opens each
bundle with UnityPy and counts class instances; a bundle with ``Mesh``
objects is a 3D mod (renderable via the existing prefab pipeline), and
a bundle with ``Sprite`` or ``Texture2D`` objects is a 2D mod (extractable
via the standard sprite path). Bundles with only ``MonoBehaviour`` /
``AssetBundle`` headers are gameplay-only and skipped.

The output of ``discover_mods()`` is a list of :class:`ModInfo` records
with bundle classifications attached — callers consume this without
re-opening bundles.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Default mod-install location per platform. macOS path is what the user
# is on; the Windows path is the documented Mohawk install location.
MODS_DIR_MAC = Path.home() / "Library/Application Support/OldWorld/Mods"
MODS_DIR_WIN = Path.home() / "Documents/My Games/OldWorld/Mods"


def find_mods_dir() -> Path | None:
    """Auto-detect the user's Old World mods directory. Returns None when
    no installation is found.
    """
    if MODS_DIR_MAC.exists():
        return MODS_DIR_MAC
    if MODS_DIR_WIN.exists():
        return MODS_DIR_WIN
    return None


@dataclass
class BundleInfo:
    """One Unity AssetBundle inside a mod's ``Assets/`` directory."""

    path: Path
    name: str  # bundle filename (no extension)
    unity_version: str  # e.g. "2022.3.39f1" or "6000.3.5f2"
    mesh_count: int = 0
    sprite_count: int = 0
    texture_count: int = 0
    skinned_mesh_renderer_count: int = 0
    animation_clip_count: int = 0

    @property
    def has_3d_content(self) -> bool:
        """True when the bundle ships renderable 3D content."""
        return self.mesh_count > 0

    @property
    def has_2d_content(self) -> bool:
        """True when the bundle ships extractable 2D sprite/texture content
        (without 3D content — 3D mods sometimes ship icon textures alongside
        meshes; in that case the 3D path covers them and we don't double-
        extract).
        """
        return not self.has_3d_content and (self.sprite_count > 0 or self.texture_count > 0)


@dataclass
class ModInfo:
    """A mod entry discovered under the user's mods directory."""

    slug: str  # kebab-case, used as the output directory name
    display_name: str
    author: str
    version: str
    description: str
    mod_dir: Path
    bundles: list[BundleInfo] = field(default_factory=list)

    @property
    def has_extractable_content(self) -> bool:
        """True when at least one bundle holds 2D or 3D content. Gameplay-
        only mods (XML overlays + DLL hooks, no asset bundles) return False.
        """
        return any(b.has_3d_content or b.has_2d_content for b in self.bundles)


_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """Turn a display name into a kebab-case slug suitable for a directory
    name. Collapses any run of non-alphanumeric characters to a single
    hyphen and strips leading/trailing hyphens.
    """
    lower = name.lower()
    slug = _SLUG_STRIP.sub("-", lower).strip("-")
    return slug or "unnamed-mod"


def _read_modinfo(mod_dir: Path) -> tuple[str, str, str, str] | None:
    """Parse ``ModInfo.xml`` for the four user-facing fields we surface:
    ``(display_name, author, version, description)``. Returns ``None``
    when the file is missing or unreadable.
    """
    modinfo_path = mod_dir / "ModInfo.xml"
    if not modinfo_path.exists():
        return None
    try:
        tree = ET.parse(modinfo_path)
        root = tree.getroot()
    except ET.ParseError as exc:
        logger.warning("Failed to parse %s: %s", modinfo_path, exc)
        return None

    def _text(tag: str) -> str:
        elem = root.find(tag)
        if elem is None or elem.text is None:
            return ""
        return elem.text.strip()

    display_name = _text("displayName") or mod_dir.name
    author = _text("author")
    version = _text("modversion")
    description = _text("description")
    return display_name, author, version, description


def _classify_bundle(bundle_path: Path) -> BundleInfo | None:
    """Open a Unity AssetBundle with UnityPy and count its content classes.
    Returns ``None`` when the file isn't a recognizable UnityFS bundle.
    """
    try:
        import UnityPy
    except ImportError:
        logger.error("UnityPy not installed; cannot classify bundles")
        return None

    try:
        env = UnityPy.load(str(bundle_path))
    except Exception as exc:
        logger.debug("Failed to load %s as UnityPy bundle: %s", bundle_path, exc)
        return None

    unity_version = getattr(env, "unity_version", "") or ""
    info = BundleInfo(
        path=bundle_path,
        name=bundle_path.name,
        unity_version=str(unity_version),
    )
    for obj in env.objects:
        type_name = obj.type.name
        if type_name == "Mesh":
            info.mesh_count += 1
        elif type_name == "Sprite":
            info.sprite_count += 1
        elif type_name == "Texture2D":
            info.texture_count += 1
        elif type_name == "SkinnedMeshRenderer":
            info.skinned_mesh_renderer_count += 1
        elif type_name == "AnimationClip":
            info.animation_clip_count += 1
    return info


def _bundle_files(mod_dir: Path) -> list[Path]:
    """List bundle files inside a mod's ``Assets/`` directory. Skips
    ``.manifest`` sidecars, hidden files, and obvious non-bundle artifacts.
    """
    assets_dir = mod_dir / "Assets"
    if not assets_dir.is_dir():
        return []
    out: list[Path] = []
    for entry in sorted(assets_dir.iterdir()):
        if entry.is_dir():
            continue
        if entry.name.startswith("."):
            continue
        if entry.suffix in {".manifest", ".meta", ".xml", ".png", ".jpg"}:
            continue
        if entry.suffix:
            # Real bundles in Old World mods ship without an extension.
            continue
        out.append(entry)
    return out


def discover_mods(mods_dir: Path | None = None) -> list[ModInfo]:
    """Walk the mods directory and return a :class:`ModInfo` per installed
    mod, with each mod's bundles classified. Mods missing ``ModInfo.xml``
    are skipped silently; bundles that fail to open are dropped from the
    returned list (with a debug log entry).

    Args:
        mods_dir: Override the auto-detected mods directory. When None,
            falls back to :func:`find_mods_dir`.

    Returns:
        A list of :class:`ModInfo` records sorted by display name. Empty
        when the mods directory doesn't exist.
    """
    if mods_dir is None:
        mods_dir = find_mods_dir()
    if mods_dir is None or not mods_dir.exists():
        return []

    mods: list[ModInfo] = []
    for entry in sorted(mods_dir.iterdir()):
        if not entry.is_dir():
            continue
        parsed = _read_modinfo(entry)
        if parsed is None:
            continue
        display_name, author, version, description = parsed
        bundles: list[BundleInfo] = []
        for bundle_path in _bundle_files(entry):
            info = _classify_bundle(bundle_path)
            if info is None:
                continue
            bundles.append(info)
        mods.append(
            ModInfo(
                slug=slugify(display_name),
                display_name=display_name,
                author=author,
                version=version,
                description=description,
                mod_dir=entry,
                bundles=bundles,
            )
        )

    mods.sort(key=lambda m: m.display_name.lower())
    return mods
