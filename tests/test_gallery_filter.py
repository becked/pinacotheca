"""Tests for the gallery deploy filter (src/pinacotheca/gallery_filter.py)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from pinacotheca.gallery_filter import (
    GALLERY_EXCLUDE_GLOBS,
    GALLERY_EXCLUDE_REASON,
    _compile_glob,
    _validate_patterns,
    matches_filter,
    write_filter_sidecar,
)


class TestMatchesFilter:
    @pytest.mark.parametrize(
        "rel_path",
        [
            "improvements/IMPROVEMENT_3D_LIBRARY_GREECE_URBAN.png",
            "improvements/IMPROVEMENT_3D_FORUM_ROME_URBAN.png",
            "improvements/IMPROVEMENT_3D_AKSUMITE_SHRINE_AKSUM_URBAN.png",
        ],
    )
    def test_urban_composites_match(self, rel_path: str) -> None:
        assert matches_filter(rel_path)

    @pytest.mark.parametrize(
        "rel_path",
        [
            # Per-render JSON sidecars under any of the 3D-output dirs.
            "improvements/IMPROVEMENT_3D_LIBRARY.json",
            "improvements/IMPROVEMENT_3D_GREECE_CAPITAL.json",
            "improvements/IMPROVEMENT_3D_LIBRARY_GREECE_URBAN.json",
            "resources/RESOURCE_3D_HORSE_HERD.json",
            "units/UNIT_3D_ARCHER.json",
        ],
    )
    def test_render_metadata_sidecars_match(self, rel_path: str) -> None:
        assert matches_filter(rel_path)

    @pytest.mark.parametrize(
        "rel_path",
        [
            "improvements/IMPROVEMENT_3D_LIBRARY.png",  # standalone improvement
            "improvements/IMPROVEMENT_3D_GREECE_CAPITAL.png",  # capital
            "improvements/IMPROVEMENT_3D_GREECE_URBAN.png",  # urban tile (only 1 underscore-separated nation)
            "improvements/IMPROVEMENT_3D_CITY.png",
            "portraits/ROME_LEADER_MALE_01.png",
            "resources/RESOURCE_3D_HORSE.png",
            # JSON sidecars in non-3D-output directories should NOT match.
            "portraits/leaderInfo.json",
        ],
    )
    def test_non_urban_composites_do_not_match(self, rel_path: str) -> None:
        assert not matches_filter(rel_path)

    def test_subdirectory_does_not_match(self) -> None:
        # `*` must not cross `/` — this protects against accidental over-matches
        # if someone restructures sprite folders.
        assert not matches_filter("improvements/sub/IMPROVEMENT_3D_LIBRARY_GREECE_URBAN.png")

    def test_custom_patterns(self) -> None:
        assert matches_filter("foo/bar.png", patterns=["foo/*.png"])
        assert not matches_filter("foo/bar.png", patterns=["baz/*.png"])


class TestValidatePatterns:
    def test_accepts_star_only(self) -> None:
        _validate_patterns(["foo/*.png", "*/bar_*_baz.png"])

    @pytest.mark.parametrize(
        "bad_pattern",
        [
            "foo?.png",
            "foo[ab].png",
            "**/foo.png",
        ],
    )
    def test_rejects_unsupported_glob_features(self, bad_pattern: str) -> None:
        with pytest.raises(ValueError, match="only `\\*` wildcards are supported"):
            _validate_patterns([bad_pattern])

    def test_module_constant_is_valid(self) -> None:
        # If this fails, GALLERY_EXCLUDE_GLOBS itself violates the contract.
        _validate_patterns(GALLERY_EXCLUDE_GLOBS)


class TestSidecar:
    def test_write_creates_file(self, tmp_path: Path) -> None:
        out = write_filter_sidecar(tmp_path)
        assert out == tmp_path / ".gallery-filter.json"
        assert out.exists()

    def test_write_contents(self, tmp_path: Path) -> None:
        out = write_filter_sidecar(tmp_path)
        data = json.loads(out.read_text())
        assert data["excludeGlobs"] == GALLERY_EXCLUDE_GLOBS
        assert data["reason"] == GALLERY_EXCLUDE_REASON
        assert "generatedAt" in data and data["generatedAt"]

    def test_write_overwrites(self, tmp_path: Path) -> None:
        write_filter_sidecar(tmp_path)
        # Tamper, then re-write
        sidecar = tmp_path / ".gallery-filter.json"
        sidecar.write_text("{}")
        write_filter_sidecar(tmp_path)
        data = json.loads(sidecar.read_text())
        assert data["excludeGlobs"] == GALLERY_EXCLUDE_GLOBS


class TestPythonTSParity:
    """Asserts the TS-side glob→regex translation produces identical matches to
    the Python ``_compile_glob`` (used by ``matches_filter``) across a
    representative path corpus.

    The TS implementation is in web/scripts/generate-manifest.ts:globToRegExp;
    here we replicate it inline so the parity check is pure-Python and
    fails loudly if either side drifts. Note: the older revision of this
    test compared against ``fnmatch.fnmatchcase`` — but stdlib fnmatch
    lets ``*`` cross ``/``, which silently broadens patterns. The Python
    implementation now mirrors TS behavior; this test pins them
    together.
    """

    @staticmethod
    def _ts_glob_to_regex(pattern: str) -> re.Pattern[str]:
        # Mirror of TS: escape regex metachars EXCEPT `*`, then `*` → `[^/]*`,
        # anchor with ^/$.
        escaped = re.sub(r"([.+^${}()|\[\]\\])", r"\\\1", pattern)
        escaped = escaped.replace("*", "[^/]*")
        return re.compile(f"^{escaped}$")

    PATHS: list[str] = [
        "improvements/IMPROVEMENT_3D_LIBRARY.png",
        "improvements/IMPROVEMENT_3D_LIBRARY_GREECE_URBAN.png",
        "improvements/IMPROVEMENT_3D_LIBRARY_PERSIA_URBAN.png",
        "improvements/IMPROVEMENT_3D_FORUM_AKSUM_URBAN.png",
        "improvements/IMPROVEMENT_3D_GREECE_CAPITAL.png",
        "improvements/IMPROVEMENT_3D_GREECE_URBAN.png",
        "portraits/IMPROVEMENT_3D_LIBRARY_GREECE_URBAN.png",
        "improvements/sub/IMPROVEMENT_3D_LIBRARY_GREECE_URBAN.png",
        "resources/RESOURCE_3D_HORSE.png",
        # Render-metadata sidecars (excluded from the gh-pages deploy).
        "improvements/IMPROVEMENT_3D_LIBRARY.json",
        "improvements/IMPROVEMENT_3D_GREECE_CAPITAL.json",
        "improvements/IMPROVEMENT_3D_LIBRARY_GREECE_URBAN.json",
        "resources/RESOURCE_3D_HORSE_HERD.json",
        "resources/RESOURCE_3D_HORSE_SOLO.json",
        "units/UNIT_3D_ARCHER.json",
        # Edge case: a JSON not in any 3D-output category — should NOT match.
        "portraits/leaderInfo.json",
        # Edge case: a JSON in a subdirectory — `*` does not cross `/`.
        "improvements/sub/IMPROVEMENT_3D_LIBRARY.json",
    ]

    @pytest.mark.parametrize("pattern", GALLERY_EXCLUDE_GLOBS)
    def test_parity(self, pattern: str) -> None:
        ts_re = self._ts_glob_to_regex(pattern)
        py_re = _compile_glob(pattern)
        for path in self.PATHS:
            py_match = bool(py_re.match(path))
            ts_match = bool(ts_re.match(path))
            assert py_match == ts_match, (
                f"pattern={pattern!r} path={path!r}: python={py_match} != ts={ts_match}"
            )
