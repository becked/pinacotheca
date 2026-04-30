"""Integration test for web/scripts/generate-manifest.ts.

Drives the TS script via ``npx tsx`` with env-var path overrides
(PINACOTHECA_SPRITES_DIR, PINACOTHECA_SIDECAR_FILE, PINACOTHECA_MANIFEST_FILE)
against fixture sprite trees, and asserts the resulting manifest excludes
URBAN composites when the sidecar is present.

Skipped if Node tooling isn't installed (npx + node_modules in web/).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = REPO_ROOT / "web"
SCRIPT = WEB_DIR / "scripts" / "generate-manifest.ts"


def _node_available() -> bool:
    return shutil.which("npx") is not None and (WEB_DIR / "node_modules" / ".bin" / "tsx").exists()


pytestmark = pytest.mark.skipif(not _node_available(), reason="npx + tsx not available")


@pytest.fixture
def fixture_tree(tmp_path: Path) -> Iterator[tuple[Path, Path, Path]]:
    """Build a tmp sprite tree, sidecar, and manifest output path."""
    sprites = tmp_path / "sprites"
    (sprites / "improvements").mkdir(parents=True)
    (sprites / "portraits").mkdir(parents=True)

    # 8x8 PNG header (sharp may try to parse, so we need at least a valid magic).
    # Use Pillow if available; otherwise the bare magic bytes will read dim 0
    # (acceptable — we only care about presence, not dimensions).
    try:
        from PIL import Image

        for path in [
            sprites / "improvements" / "IMPROVEMENT_3D_LIBRARY.png",
            sprites / "improvements" / "IMPROVEMENT_3D_LIBRARY_GREECE_URBAN.png",
            sprites / "improvements" / "IMPROVEMENT_3D_FORUM_ROME_URBAN.png",
            sprites / "portraits" / "ROME_LEADER_MALE_01.png",
        ]:
            Image.new("RGBA", (8, 8)).save(path)
    except ImportError:
        for path in [
            sprites / "improvements" / "IMPROVEMENT_3D_LIBRARY.png",
            sprites / "improvements" / "IMPROVEMENT_3D_LIBRARY_GREECE_URBAN.png",
            sprites / "improvements" / "IMPROVEMENT_3D_FORUM_ROME_URBAN.png",
            sprites / "portraits" / "ROME_LEADER_MALE_01.png",
        ]:
            path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    sidecar = tmp_path / ".gallery-filter.json"
    manifest_out = tmp_path / "manifest.json"

    yield sprites, sidecar, manifest_out


def _run_manifest_script(
    sprites: Path, sidecar: Path, manifest_out: Path
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PINACOTHECA_SPRITES_DIR"] = str(sprites)
    env["PINACOTHECA_SIDECAR_FILE"] = str(sidecar)
    env["PINACOTHECA_MANIFEST_FILE"] = str(manifest_out)
    return subprocess.run(
        ["npx", "tsx", str(SCRIPT)],
        cwd=WEB_DIR,
        env=env,
        capture_output=True,
        text=True,
    )


class TestManifestFilter:
    def test_filter_applied_when_sidecar_present(
        self, fixture_tree: tuple[Path, Path, Path]
    ) -> None:
        sprites, sidecar, manifest_out = fixture_tree
        from pinacotheca.gallery_filter import write_filter_sidecar

        write_filter_sidecar(sidecar.parent)
        # write_filter_sidecar creates `<dir>/.gallery-filter.json`, so the
        # path matches our env override.
        assert sidecar.exists()

        result = _run_manifest_script(sprites, sidecar, manifest_out)
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert manifest_out.exists()

        manifest = json.loads(manifest_out.read_text())
        paths = {s["path"] for s in manifest["sprites"]}

        assert "sprites/improvements/IMPROVEMENT_3D_LIBRARY.png" in paths
        assert "sprites/portraits/ROME_LEADER_MALE_01.png" in paths
        assert "sprites/improvements/IMPROVEMENT_3D_LIBRARY_GREECE_URBAN.png" not in paths
        assert "sprites/improvements/IMPROVEMENT_3D_FORUM_ROME_URBAN.png" not in paths
        assert manifest["totalSprites"] == 2

    def test_hard_fail_when_sidecar_missing_but_sprites_present(
        self, fixture_tree: tuple[Path, Path, Path]
    ) -> None:
        sprites, sidecar, manifest_out = fixture_tree
        # Don't write the sidecar.
        assert not sidecar.exists()

        result = _run_manifest_script(sprites, sidecar, manifest_out)
        assert result.returncode == 1
        assert ".gallery-filter.json" in result.stderr
        assert "pinacotheca" in result.stderr

    def test_no_filter_when_sprites_dir_missing(self, tmp_path: Path) -> None:
        sprites = tmp_path / "nonexistent"
        sidecar = tmp_path / ".gallery-filter.json"
        manifest_out = tmp_path / "manifest.json"

        result = _run_manifest_script(sprites, sidecar, manifest_out)
        # The script exits 1 on missing sprites/ regardless of sidecar
        # (separate guard at the top of generateManifest()).
        assert result.returncode == 1
        assert "Sprites directory not found" in result.stderr
