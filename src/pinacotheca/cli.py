"""
Command-line interface for Pinacotheca.

Provides commands for extracting sprites, generating galleries, and deploying to GitHub Pages.
"""

import argparse
import subprocess
import sys
from pathlib import Path

from pinacotheca.extractor import (
    extract_improvement_meshes,
    extract_sprites,
    extract_unit_meshes,
)


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


def deploy() -> None:
    """Deploy gallery to GitHub Pages using ghp-import."""
    parser = argparse.ArgumentParser(
        description="Deploy gallery to GitHub Pages",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This command uses ghp-import to push the extracted gallery to the gh-pages branch.
GitHub Pages should be configured to serve from the gh-pages branch.

Examples:
  pinacotheca-deploy                    # Deploy ./extracted to gh-pages
  pinacotheca-deploy -o ~/my-sprites    # Deploy custom directory
  pinacotheca-deploy --dry-run          # Preview without pushing
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

    args = parser.parse_args()

    # Verify directory exists and has content
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

    # Count files
    sprite_count = sum(1 for _ in sprites_dir.rglob("*.png"))
    print(f"Deploying gallery with {sprite_count:,} sprites...")

    if args.dry_run:
        print(f"\nDry run - would deploy {args.output} to branch '{args.branch}'")
        print("Files that would be deployed:")
        for f in sorted(args.output.rglob("*"))[:20]:
            if f.is_file():
                print(f"  {f.relative_to(args.output)}")
        print("  ...")
        return

    # Run ghp-import
    cmd = [
        "ghp-import",
        "-n",  # Include .nojekyll
        "-p",  # Push after import
        "-f",  # Force push
        "-b",
        args.branch,
        "-m",
        args.message,
        str(args.output),
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"Successfully deployed to '{args.branch}' branch!")
        print("\nYour gallery should be available at:")
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

    try:
        subprocess.run(["npm", "run", "build"], cwd=web_dir, check=True)
    except FileNotFoundError:
        print("ERROR: npm not found. Install Node.js first.", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)


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
