"""Integration tests for `pinacotheca-deploy` (src/pinacotheca/cli.py:deploy).

Uses ``--dry-run`` against a fixture extracted/ tree containing both URBAN and
non-URBAN files; asserts the rsync stage drops URBAN files but keeps the rest.
Requires ``rsync`` on PATH (preinstalled on macOS / most Linux).
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from pinacotheca.cli import _stage_with_filter
from pinacotheca.gallery_filter import GALLERY_EXCLUDE_GLOBS, write_filter_sidecar

pytestmark = pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync not on PATH")


@pytest.fixture
def fixture_extracted(tmp_path: Path) -> Iterator[Path]:
    """A minimal extracted/ tree containing one URBAN composite, one standalone
    improvement, plus the index.html + sidecar that deploy() expects."""
    root = tmp_path / "extracted"
    sprites = root / "sprites"
    (sprites / "improvements").mkdir(parents=True)
    (sprites / "portraits").mkdir(parents=True)

    (sprites / "improvements" / "IMPROVEMENT_3D_LIBRARY.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"a" * 100
    )
    (sprites / "improvements" / "IMPROVEMENT_3D_LIBRARY_GREECE_URBAN.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"b" * 100
    )
    (sprites / "improvements" / "IMPROVEMENT_3D_FORUM_ROME_URBAN.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"c" * 100
    )
    (sprites / "portraits" / "ROME_LEADER_MALE_01.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"d" * 50
    )

    (root / "index.html").write_text("<html></html>")
    write_filter_sidecar(root)

    yield root


class TestStageWithFilter:
    def test_excludes_urban_composites(self, fixture_extracted: Path, tmp_path: Path) -> None:
        staging = tmp_path / "staging"
        staging.mkdir()

        _stage_with_filter(fixture_extracted, staging, GALLERY_EXCLUDE_GLOBS, verbose=False)

        staged_files = {str(p.relative_to(staging)) for p in staging.rglob("*") if p.is_file()}

        assert "sprites/improvements/IMPROVEMENT_3D_LIBRARY.png" in staged_files
        assert "sprites/portraits/ROME_LEADER_MALE_01.png" in staged_files
        assert "index.html" in staged_files

        assert "sprites/improvements/IMPROVEMENT_3D_LIBRARY_GREECE_URBAN.png" not in staged_files
        assert "sprites/improvements/IMPROVEMENT_3D_FORUM_ROME_URBAN.png" not in staged_files

    def test_no_excludes_keeps_everything(self, fixture_extracted: Path, tmp_path: Path) -> None:
        staging = tmp_path / "staging"
        staging.mkdir()

        _stage_with_filter(fixture_extracted, staging, [], verbose=False)

        staged_files = {str(p.relative_to(staging)) for p in staging.rglob("*") if p.is_file()}

        # All four PNGs should be present when no excludes apply
        assert "sprites/improvements/IMPROVEMENT_3D_LIBRARY.png" in staged_files
        assert "sprites/improvements/IMPROVEMENT_3D_LIBRARY_GREECE_URBAN.png" in staged_files
        assert "sprites/improvements/IMPROVEMENT_3D_FORUM_ROME_URBAN.png" in staged_files

    def test_unrelated_pattern_is_no_op(self, fixture_extracted: Path, tmp_path: Path) -> None:
        staging = tmp_path / "staging"
        staging.mkdir()

        _stage_with_filter(fixture_extracted, staging, ["nonexistent/*.png"], verbose=False)

        staged_files = {str(p.relative_to(staging)) for p in staging.rglob("*") if p.is_file()}
        assert "sprites/improvements/IMPROVEMENT_3D_LIBRARY_GREECE_URBAN.png" in staged_files


class TestDeployDryRun:
    """End-to-end through deploy() with --dry-run. Skips ghp-import entirely
    since --dry-run returns before it runs."""

    def _run_deploy(self, output_dir: Path, *extra_args: str) -> int:
        from pinacotheca.cli import deploy

        old_argv = sys.argv
        sys.argv = [
            "pinacotheca-deploy",
            "-o",
            str(output_dir),
            "--dry-run",
            "--no-optimize",  # skip oxipng for speed; tested separately
            *extra_args,
        ]
        try:
            deploy()
            return 0
        except SystemExit as e:
            return int(e.code) if e.code is not None else 0
        finally:
            sys.argv = old_argv

    def test_dry_run_succeeds(
        self, fixture_extracted: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = self._run_deploy(fixture_extracted)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Filter excluded" in out
        assert "Dry run" in out

    def test_missing_sidecar_fails_loud(
        self, fixture_extracted: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (fixture_extracted / ".gallery-filter.json").unlink()
        rc = self._run_deploy(fixture_extracted)
        assert rc == 1
        err = capsys.readouterr().err
        assert ".gallery-filter.json" in err
        assert "pinacotheca" in err  # mentions running pinacotheca to fix

    def test_no_filter_flag_warns(
        self, fixture_extracted: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = self._run_deploy(fixture_extracted, "--no-filter")
        assert rc == 0
        out = capsys.readouterr().out
        assert "--no-filter" in out
        assert "1 GB" in out  # warning text mentions the limit
