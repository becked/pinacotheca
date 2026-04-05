#!/usr/bin/env python3
"""Bump the project version in pyproject.toml and update CHANGELOG.md."""

import re
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <version>")
        print("Example: python scripts/bump-version.py 1.1.0")
        sys.exit(1)

    new_version = sys.argv[1]

    # Validate version format
    if not re.match(r"^\d+\.\d+\.\d+$", new_version):
        print(f"ERROR: Invalid version format '{new_version}'. Expected X.Y.Z", file=sys.stderr)
        sys.exit(1)

    # Update pyproject.toml
    pyproject_text = PYPROJECT.read_text()
    old_match = re.search(r'^version = "(.+?)"', pyproject_text, re.MULTILINE)
    if not old_match:
        print("ERROR: Could not find version in pyproject.toml", file=sys.stderr)
        sys.exit(1)

    old_version = old_match.group(1)
    if old_version == new_version:
        print(f"Version is already {new_version}", file=sys.stderr)
        sys.exit(1)

    pyproject_text = pyproject_text.replace(
        f'version = "{old_version}"',
        f'version = "{new_version}"',
        1,
    )
    PYPROJECT.write_text(pyproject_text)
    print(f"Updated pyproject.toml: {old_version} -> {new_version}")

    # Update CHANGELOG.md
    if CHANGELOG.exists():
        changelog_text = CHANGELOG.read_text()
        today = date.today().isoformat()
        # Replace [Unreleased] header with versioned header, add new Unreleased
        changelog_text = changelog_text.replace(
            "## [Unreleased]",
            f"## [Unreleased]\n\n## [{new_version}] - {today}",
            1,
        )
        CHANGELOG.write_text(changelog_text)
        print(f"Updated CHANGELOG.md with [{new_version}] - {today}")
    else:
        print("WARNING: CHANGELOG.md not found, skipping")

    print()
    print("Next steps:")
    print("  1. Review changes: git diff")
    print(f"  2. Commit: git commit -am 'Bump version to {new_version}'")
    print(f"  3. Tag: git tag v{new_version}")


if __name__ == "__main__":
    main()
