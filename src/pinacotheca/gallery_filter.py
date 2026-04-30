"""Gallery deploy filter — patterns excluded from the public SvelteKit manifest
and the gh-pages deploy.

Files matching these globs stay on disk in ``extracted/sprites/`` (per-ankh, our
sister hex-map renderer, consumes them) but are NOT shipped to the public gallery,
because the deployed site is bound by GitHub Pages' 1 GB cap.

Python is the source of truth: ``pinacotheca-deploy`` reads
:data:`GALLERY_EXCLUDE_GLOBS` directly. A JSON sidecar
(``extracted/.gallery-filter.json``) is written for the TS-side consumer
(``web/scripts/generate-manifest.ts``) only.

Pattern contract: only ``*`` wildcards. No ``?``, no ``[...]``, no ``**``. ``*``
does not match ``/``. This restriction keeps the Python (``fnmatch.fnmatchcase``)
and TS (regex ``[^/]*``) implementations provably equivalent — see the parity
test in ``tests/test_gallery_filter.py``.
"""

from __future__ import annotations

import fnmatch
import json
from datetime import UTC, datetime
from pathlib import Path

GALLERY_EXCLUDE_GLOBS: list[str] = [
    "improvements/IMPROVEMENT_3D_*_*_URBAN.png",
]

GALLERY_EXCLUDE_REASON: str = (
    "Per-(improvement, nation) urban composites — used by per-ankh's atlas "
    "renderer (sister tool) but excluded from the gh-pages gallery deploy "
    "because they push the site over GitHub Pages' 1 GB limit."
)


def _validate_patterns(patterns: list[str]) -> None:
    forbidden = ("?", "[", "**")
    for p in patterns:
        for c in forbidden:
            if c in p:
                raise ValueError(
                    f"GALLERY_EXCLUDE_GLOBS pattern {p!r} uses {c!r}; "
                    "only `*` wildcards are supported (TS-parity constraint)."
                )


_validate_patterns(GALLERY_EXCLUDE_GLOBS)


def matches_filter(rel_path: str, patterns: list[str] | None = None) -> bool:
    """Return True if ``rel_path`` matches any exclusion glob.

    ``rel_path`` is interpreted relative to ``extracted/sprites/`` and must use
    posix-style separators.
    """
    pats = patterns if patterns is not None else GALLERY_EXCLUDE_GLOBS
    return any(fnmatch.fnmatchcase(rel_path, p) for p in pats)


def write_filter_sidecar(extracted_dir: Path) -> Path:
    """Write ``extracted/.gallery-filter.json``. Always overwrites."""
    out = extracted_dir / ".gallery-filter.json"
    out.write_text(
        json.dumps(
            {
                "generatedAt": datetime.now(UTC).isoformat(),
                "excludeGlobs": GALLERY_EXCLUDE_GLOBS,
                "reason": GALLERY_EXCLUDE_REASON,
            },
            indent=2,
        )
        + "\n"
    )
    return out
