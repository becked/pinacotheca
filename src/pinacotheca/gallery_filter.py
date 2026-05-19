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

import json
import re
from datetime import UTC, datetime
from pathlib import Path

GALLERY_EXCLUDE_GLOBS: list[str] = [
    "improvements/IMPROVEMENT_3D_*_*_URBAN.png",
    "improvements/*.json",
    "resources/*.json",
    "units/*.json",
]

GALLERY_EXCLUDE_REASON: str = (
    "Per-(improvement, nation) urban composites — used by per-ankh's atlas "
    "renderer (sister tool) but excluded from the gh-pages gallery deploy "
    "because they push the site over GitHub Pages' 1 GB limit. "
    "Render-metadata JSON sidecars (`*.json` next to each 3D PNG) are "
    "consumed by per-ankh from the local `extracted/` tree; they are not "
    "needed by the deployed SvelteKit gallery so are excluded from the "
    "gh-pages bundle. Additional dynamic entries may be appended at "
    "extraction time to gate mod content behind per-mod author approval — "
    "see `pinacotheca.mod_extractor.APPROVED_AUTHORS_BY_MOD`."
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


def _compile_glob(pattern: str) -> re.Pattern[str]:
    """Translate a single-`*` glob to an anchored regex where `*` does
    not cross `/`. Mirrors the TS-side ``globToRegExp`` in
    ``web/scripts/generate-manifest.ts`` byte-for-byte so the parity
    test in ``tests/test_gallery_filter.py`` is a pure-Python check.

    NOTE: Python's stdlib ``fnmatch.fnmatchcase`` is *not* used here — it
    lets ``*`` cross ``/``, which would silently broaden patterns like
    ``improvements/*.json`` to also match ``improvements/sub/foo.json``
    and diverge from the TS deploy filter.
    """
    # Escape regex metachars except `*`.
    escaped = re.sub(r"([.+^${}()|\[\]\\])", r"\\\1", pattern)
    escaped = escaped.replace("*", "[^/]*")
    return re.compile(f"^{escaped}$")


_COMPILED: list[re.Pattern[str]] = [_compile_glob(p) for p in GALLERY_EXCLUDE_GLOBS]


def matches_filter(rel_path: str, patterns: list[str] | None = None) -> bool:
    """Return True if ``rel_path`` matches any exclusion glob.

    ``rel_path`` is interpreted relative to ``extracted/sprites/`` and must use
    posix-style separators. ``*`` does not cross ``/``.
    """
    if patterns is None:
        return any(p.match(rel_path) is not None for p in _COMPILED)
    compiled = [_compile_glob(p) for p in patterns]
    return any(p.match(rel_path) is not None for p in compiled)


def write_filter_sidecar(extracted_dir: Path, extra_globs: list[str] | None = None) -> Path:
    """Write ``extracted/.gallery-filter.json``. Always overwrites.

    ``extra_globs`` is appended after the static :data:`GALLERY_EXCLUDE_GLOBS`
    so the same pattern contract (``*``-only, no ``?``/``[``/``**``,
    ``*`` does not cross ``/``) is enforced via :func:`_validate_patterns`.
    The dynamic extras let callers — currently the mod extractor's
    artist-opt-out support — append per-file exclusions without
    introducing a parallel filter mechanism.
    """
    extras: list[str] = list(extra_globs or [])
    if extras:
        _validate_patterns(extras)
    combined = list(GALLERY_EXCLUDE_GLOBS) + extras
    out = extracted_dir / ".gallery-filter.json"
    out.write_text(
        json.dumps(
            {
                "generatedAt": datetime.now(UTC).isoformat(),
                "excludeGlobs": combined,
                "reason": GALLERY_EXCLUDE_REASON,
            },
            indent=2,
        )
        + "\n"
    )
    return out
