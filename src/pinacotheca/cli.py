"""
Command-line interface for Pinacotheca.

Provides commands for extracting sprites, generating galleries, and deploying to GitHub Pages.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from pinacotheca.extractor import (
    extract_improvement_meshes,
    extract_rural_composite_meshes,
    extract_sprites,
    extract_terrain_tiles,
    extract_unit_meshes,
    extract_urban_composite_meshes,
    extract_vegetation_meshes,
)
from pinacotheca.gallery_filter import GALLERY_EXCLUDE_GLOBS, write_filter_sidecar
from pinacotheca.mod_extractor import compute_excluded_mod_globs, extract_mod_assets


def main() -> None:
    """Main entry point - extract sprites from Old World game assets."""
    parser = argparse.ArgumentParser(
        description="Extract sprites from Old World game assets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  pinacotheca                    # Auto-detect game and extract to ./extracted
  pinacotheca -o ~/sprites       # Extract to custom directory
  pinacotheca --game-data /path  # Specify game data location
        """,
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path.cwd() / "extracted",
        help="Output directory (default: ./extracted)",
    )
    parser.add_argument(
        "-g",
        "--game-data",
        type=Path,
        default=None,
        help="Path to game's Data directory (auto-detected if not specified)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress progress output",
    )
    parser.add_argument(
        "--no-meshes",
        action="store_true",
        help="Skip 3D mesh extraction (renders unit and building models to 2D images)",
    )
    parser.add_argument(
        "--no-mods",
        action="store_true",
        help="Skip extraction of installed mods' visual assets",
    )

    args = parser.parse_args()

    try:
        extract_sprites(
            game_data=args.game_data,
            output_dir=args.output,
            verbose=not args.quiet,
        )

        if not args.no_meshes:
            extract_unit_meshes(
                game_data=args.game_data,
                output_dir=args.output,
                verbose=not args.quiet,
            )
            extract_improvement_meshes(
                game_data=args.game_data,
                output_dir=args.output,
                verbose=not args.quiet,
            )
            extract_urban_composite_meshes(
                game_data=args.game_data,
                output_dir=args.output,
                verbose=not args.quiet,
            )
            extract_rural_composite_meshes(
                game_data=args.game_data,
                output_dir=args.output,
                verbose=not args.quiet,
            )
            extract_terrain_tiles(
                game_data=args.game_data,
                output_dir=args.output,
                verbose=not args.quiet,
            )
            extract_vegetation_meshes(
                game_data=args.game_data,
                output_dir=args.output,
                verbose=not args.quiet,
            )

        if not args.no_mods:
            extract_mod_assets(
                output_dir=args.output,
                verbose=not args.quiet,
            )

        extra_globs = compute_excluded_mod_globs(args.output)
        sidecar = write_filter_sidecar(args.output, extra_globs=extra_globs)
        if not args.quiet:
            print(f"Wrote gallery filter sidecar: {sidecar}")
            if extra_globs:
                print(f"  + {len(extra_globs)} mod sprite(s) gated behind APPROVED_AUTHORS")

    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except ImportError:
        sys.exit(1)


def gallery() -> None:
    """Regenerate legacy HTML gallery from existing sprites."""
    from pinacotheca.gallery import generate_gallery

    parser = argparse.ArgumentParser(
        description="Generate standalone HTML gallery from extracted sprites",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path.cwd() / "output" / "gallery",
        help="Output directory for gallery (default: ./output/gallery)",
    )
    parser.add_argument(
        "-s",
        "--sprites",
        type=Path,
        default=Path.cwd() / "extracted" / "sprites",
        help="Directory containing categorized sprites (default: ./extracted/sprites)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress progress output",
    )

    args = parser.parse_args()

    result = generate_gallery(
        output_dir=args.output,
        sprites_dir=args.sprites,
        verbose=not args.quiet,
    )
    if result is None:
        sys.exit(1)


def _dir_size_bytes(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _file_count(path: Path) -> int:
    return sum(1 for f in path.rglob("*") if f.is_file())


def _format_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} B"


def _stage_with_filter(
    source: Path, staging: Path, exclude_globs: list[str], *, verbose: bool = True
) -> None:
    """Mirror ``source/`` into ``staging/`` via rsync, omitting paths under
    ``sprites/`` that match any glob in ``exclude_globs``.

    Uses ``-aL --copy-unsafe-links`` to materialize symlinks (gh-pages can't
    serve dangling links). xattrs aren't copied because ``-a`` on macOS and
    GNU rsync defaults excludes them.
    """
    cmd = [
        "rsync",
        "-aL",
        "--copy-unsafe-links",
        "--delete",
    ]
    for glob in exclude_globs:
        cmd.append(f"--exclude=sprites/{glob}")
    cmd.append(f"{source}/")
    cmd.append(f"{staging}/")
    if verbose:
        print(f"Staging via rsync ({len(exclude_globs)} exclude pattern(s))...")
    subprocess.run(cmd, check=True)


def _run_oxipng(directory: Path, *, verbose: bool = True) -> tuple[int, int]:
    """Optimize PNGs under ``directory`` in place. Returns (before, after) bytes."""
    before = _dir_size_bytes(directory)
    threads = str(os.cpu_count() or 4)
    # -o 2 (default) gives ~95% of -o 4's savings at <30% the wall time;
    # benchmarked on these renders, -o 4 saves only 0.3 percentage points
    # extra at 3x the runtime. Not worth it on a 4500-file deploy.
    cmd = [
        "oxipng",
        "-o",
        "2",
        "--strip",
        "safe",
        "-t",
        threads,
        "-r",
        "--preserve",
        "-q",
        str(directory),
    ]
    if verbose:
        print(f"Running oxipng -o 2 on {directory} (-t {threads})...")
    subprocess.run(cmd, check=True)
    after = _dir_size_bytes(directory)
    return before, after


def deploy() -> None:
    """Deploy gallery to GitHub Pages using ghp-import.

    Stages ``--output`` to a temp directory via ``rsync``, applying the gallery
    filter (see ``src/pinacotheca/gallery_filter.py``) and optionally running
    ``oxipng`` for additional compression, before handing the staged tree to
    ``ghp-import``. Local ``extracted/`` is never modified.
    """
    parser = argparse.ArgumentParser(
        description="Deploy gallery to GitHub Pages",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This command stages ./extracted to a temp directory (filtering large local-only
assets — see src/pinacotheca/gallery_filter.py), optionally compresses PNGs with
oxipng, then uses ghp-import to push the staged tree to the gh-pages branch.

Examples:
  pinacotheca-deploy                    # Filter + oxipng + push
  pinacotheca-deploy --no-optimize      # Skip oxipng pass
  pinacotheca-deploy --no-filter        # Emergency: deploy everything (over Pages cap!)
  pinacotheca-deploy --dry-run          # Stage and report; don't push
        """,
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path.cwd() / "extracted",
        help="Directory to deploy (default: ./extracted)",
    )
    from importlib.metadata import version

    default_message = f"Deploy gallery v{version('pinacotheca')}"
    parser.add_argument(
        "-m",
        "--message",
        default=default_message,
        help=f"Commit message for gh-pages (default: '{default_message}')",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Preview what would be deployed without pushing",
    )
    parser.add_argument(
        "-b",
        "--branch",
        default="gh-pages",
        help="Branch to deploy to (default: gh-pages)",
    )
    parser.add_argument(
        "--no-optimize",
        action="store_true",
        help="Skip the oxipng compression pass on staged PNGs",
    )
    parser.add_argument(
        "--no-filter",
        action="store_true",
        help="Emergency override: deploy everything, ignoring gallery_filter.py "
        "(WARNING: likely exceeds GitHub Pages' 1 GB site limit)",
    )

    args = parser.parse_args()

    if not args.output.exists():
        print(f"ERROR: Directory not found: {args.output}", file=sys.stderr)
        sys.exit(1)

    index_file = args.output / "index.html"
    if not index_file.exists():
        print(f"ERROR: No index.html found in {args.output}", file=sys.stderr)
        print("Run 'pinacotheca-web-build' first to generate the gallery.", file=sys.stderr)
        sys.exit(1)

    sprites_dir = args.output / "sprites"
    if not sprites_dir.exists():
        print(f"ERROR: No sprites/ directory found in {args.output}", file=sys.stderr)
        sys.exit(1)

    sidecar = args.output / ".gallery-filter.json"
    if not sidecar.exists():
        print(f"ERROR: {sidecar} not found.", file=sys.stderr)
        print(
            "Run `pinacotheca` first to generate it (the SvelteKit manifest reads it too).",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.no_filter:
        print("WARNING: --no-filter is set. Deploying every file in --output.")
        print("         This will likely exceed GitHub Pages' 1 GB site limit.")
        excludes: list[str] = []
    else:
        # Read from the sidecar so dynamic exclusions (artist opt-outs
        # appended at extraction time, see mod_extractor.EXCLUDED_AUTHORS)
        # are honored alongside the static GALLERY_EXCLUDE_GLOBS list.
        try:
            sidecar_data = json.loads(sidecar.read_text())
            excludes = list(sidecar_data.get("excludeGlobs") or [])
        except (OSError, ValueError) as e:
            print(f"ERROR: Failed to read sidecar {sidecar}: {e}", file=sys.stderr)
            sys.exit(1)

    if shutil.which("rsync") is None:
        print("ERROR: rsync not found on PATH.", file=sys.stderr)
        print("rsync is preinstalled on macOS and most Linux distros.", file=sys.stderr)
        sys.exit(1)

    pre_size = _dir_size_bytes(args.output)
    pre_count = _file_count(args.output)
    print(f"Source: {args.output}  ({pre_count:,} files, {_format_bytes(pre_size)})")

    with tempfile.TemporaryDirectory(prefix="pinacotheca-deploy-") as staging_str:
        staging = Path(staging_str)

        try:
            _stage_with_filter(args.output, staging, excludes, verbose=True)
        except subprocess.CalledProcessError as e:
            print(f"ERROR: rsync failed (exit {e.returncode})", file=sys.stderr)
            sys.exit(1)

        staged_size = _dir_size_bytes(staging)
        staged_count = _file_count(staging)
        if excludes:
            excluded_count = pre_count - staged_count
            excluded_bytes = pre_size - staged_size
            if excluded_count == 0:
                print(
                    f"  Filter patterns matched 0 files (already absent or filter is current): "
                    f"{', '.join(excludes)}"
                )
            else:
                print(
                    f"  Filter excluded {excluded_count:,} files "
                    f"({_format_bytes(excluded_bytes)}): {', '.join(excludes)}"
                )

        if not args.no_optimize:
            if shutil.which("oxipng") is None:
                print(
                    "  oxipng not found — skipping compression. "
                    "Install with: brew install oxipng (macOS)"
                )
            else:
                try:
                    before, after = _run_oxipng(staging / "sprites", verbose=True)
                    saved = before - after
                    pct = (saved / before * 100.0) if before else 0.0
                    print(
                        f"  oxipng saved {_format_bytes(saved)} "
                        f"({pct:.1f}% across {staging / 'sprites'})"
                    )
                except subprocess.CalledProcessError as e:
                    print(
                        f"  WARNING: oxipng failed (exit {e.returncode}); "
                        "continuing with uncompressed PNGs",
                        file=sys.stderr,
                    )

        final_size = _dir_size_bytes(staging)
        final_count = _file_count(staging)
        cap_bytes = 1024 * 1024 * 1024  # GitHub Pages' 1 GB site limit
        cap_pct = final_size / cap_bytes * 100.0
        print(
            f"\nStaged: {final_count:,} files, {_format_bytes(final_size)} "
            f"({cap_pct:.1f}% of GitHub Pages' 1 GB site limit)"
        )
        if final_size > cap_bytes:
            print(
                "WARNING: staged size exceeds 1 GB. GitHub Pages may refuse to publish.",
                file=sys.stderr,
            )

        if args.dry_run:
            print(f"\nDry run — would deploy {staging} to branch '{args.branch}'")
            print("Sample files that would be deployed:")
            for f in sorted(staging.rglob("*"))[:20]:
                if f.is_file():
                    print(f"  {f.relative_to(staging)}")
            return

        cmd = [
            "ghp-import",
            "-n",  # Include .nojekyll
            "-p",  # Push after import
            "-f",  # Force push
            "-b",
            args.branch,
            "-m",
            args.message,
            str(staging),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            print(f"\nSuccessfully deployed to '{args.branch}' branch!")
            print("Your gallery should be available at:")
            print("  https://<username>.github.io/<repo>/")
        except FileNotFoundError:
            print("ERROR: ghp-import not found.", file=sys.stderr)
            print("Install with: pip install ghp-import", file=sys.stderr)
            sys.exit(1)
        except subprocess.CalledProcessError as e:
            print(f"ERROR: ghp-import failed: {e.stderr}", file=sys.stderr)
            sys.exit(1)


def _find_web_dir() -> Path:
    """Locate the web/ directory relative to the project root."""
    # Walk up from this file to find the repo root containing web/
    cli_path = Path(__file__).resolve()
    for parent in cli_path.parents:
        candidate = parent / "web"
        if candidate.is_dir() and (candidate / "package.json").exists():
            return candidate
    # Fallback: relative to cwd
    cwd_candidate = Path.cwd() / "web"
    if cwd_candidate.is_dir():
        return cwd_candidate
    raise FileNotFoundError(
        "Could not find web/ directory. Run from the project root or use --web-dir."
    )


def web_dev() -> None:
    """Run the SvelteKit development server."""
    parser = argparse.ArgumentParser(
        description="Run the SvelteKit gallery dev server",
    )
    parser.add_argument(
        "--web-dir",
        type=Path,
        default=None,
        help="Path to web/ directory (auto-detected if not specified)",
    )

    args = parser.parse_args()

    try:
        web_dir = args.web_dir or _find_web_dir()
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        subprocess.run(["npm", "run", "dev"], cwd=web_dir, check=True)
    except KeyboardInterrupt:
        pass
    except FileNotFoundError:
        print("ERROR: npm not found. Install Node.js first.", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)


def web_build() -> None:
    """Build the SvelteKit gallery for production."""
    parser = argparse.ArgumentParser(
        description="Build the SvelteKit gallery (outputs to extracted/)",
    )
    parser.add_argument(
        "--web-dir",
        type=Path,
        default=None,
        help="Path to web/ directory (auto-detected if not specified)",
    )

    args = parser.parse_args()

    try:
        web_dir = args.web_dir or _find_web_dir()
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # The SvelteKit static adapter wipes extracted/ before writing its build
    # output, which deletes any sidecar pinacotheca wrote. Write it both
    # before (so `npm run manifest` can read it) and after (so deploy() can).
    extracted_dir = web_dir.parent / "extracted"
    if (extracted_dir / "sprites").exists():
        write_filter_sidecar(extracted_dir, extra_globs=compute_excluded_mod_globs(extracted_dir))

    try:
        subprocess.run(["npm", "run", "build"], cwd=web_dir, check=True)
    except FileNotFoundError:
        print("ERROR: npm not found. Install Node.js first.", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)

    if extracted_dir.exists():
        sidecar = write_filter_sidecar(
            extracted_dir, extra_globs=compute_excluded_mod_globs(extracted_dir)
        )
        print(f"Restored gallery filter sidecar: {sidecar}")


def mods() -> None:
    """Extract assets from installed Old World mods without re-running the
    base-game extraction. Useful when you've installed a new mod and want
    to refresh just its outputs.
    """
    parser = argparse.ArgumentParser(
        description="Extract visual assets from installed Old World mods",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path.cwd() / "extracted",
        help="Output directory (default: ./extracted)",
    )
    parser.add_argument(
        "--mods-dir",
        type=Path,
        default=None,
        help="Mods directory (auto-detected if not specified)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress progress output",
    )

    args = parser.parse_args()
    try:
        extract_mod_assets(
            output_dir=args.output,
            mods_dir=args.mods_dir,
            verbose=not args.quiet,
        )
        extra_globs = compute_excluded_mod_globs(args.output)
        sidecar = write_filter_sidecar(args.output, extra_globs=extra_globs)
        if not args.quiet:
            print(f"\nWrote gallery filter sidecar: {sidecar}")
            if extra_globs:
                print(f"  + {len(extra_globs)} mod sprite(s) gated behind APPROVED_AUTHORS")
    except ImportError:
        sys.exit(1)


def atlas() -> None:
    """Generate texture atlases from extracted sprites."""
    parser = argparse.ArgumentParser(
        description="Generate texture atlases from extracted sprites for map rendering",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  pinacotheca-atlas                          # Generate all atlases
  pinacotheca-atlas -c terrain height        # Only terrain and height
  pinacotheca-atlas --lossy 95               # Lossy WebP for smaller files
        """,
    )
    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        default=Path.cwd() / "extracted" / "sprites",
        help="Directory containing categorized sprites (default: ./extracted/sprites)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path.cwd() / "output" / "atlases",
        help="Output directory for atlas files (default: ./output/atlases)",
    )
    parser.add_argument(
        "-c",
        "--categories",
        nargs="+",
        default=None,
        help="Atlas categories to generate (default: all). "
        "Choices: terrain, height, improvement, resource, specialist, city",
    )
    parser.add_argument(
        "--lossy",
        type=int,
        default=None,
        metavar="QUALITY",
        help="Use lossy WebP at given quality 0-100 (default: lossless)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress progress output",
    )

    args = parser.parse_args()

    if not args.input.is_dir():
        print(f"ERROR: Sprites directory not found: {args.input}", file=sys.stderr)
        print("Run 'pinacotheca' first to extract sprites.", file=sys.stderr)
        sys.exit(1)

    from pinacotheca.atlas import generate_atlases

    try:
        results = generate_atlases(
            sprites_dir=args.input,
            output_dir=args.output,
            categories=args.categories,
            lossy_quality=args.lossy,
            verbose=not args.quiet,
        )

        if not args.quiet:
            total = sum(results.values())
            print(f"\nDone! {total} sprites across {len(results)} atlases → {args.output}")

    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
