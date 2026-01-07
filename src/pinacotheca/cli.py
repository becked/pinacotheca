"""
Command-line interface for Pinacotheca.

Provides commands for extracting sprites, generating galleries, and deploying to GitHub Pages.
"""

import argparse
import subprocess
import sys
from pathlib import Path

from pinacotheca.extractor import extract_sprites
from pinacotheca.gallery import generate_gallery


def main() -> None:
    """Main entry point - extract sprites and generate gallery."""
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
        "--no-gallery",
        action="store_true",
        help="Skip gallery generation",
    )

    args = parser.parse_args()

    try:
        extract_sprites(
            game_data=args.game_data,
            output_dir=args.output,
            verbose=not args.quiet,
        )

        if not args.no_gallery:
            generate_gallery(output_dir=args.output, verbose=not args.quiet)

    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except ImportError:
        sys.exit(1)


def gallery() -> None:
    """Regenerate gallery from existing sprites."""
    parser = argparse.ArgumentParser(
        description="Generate HTML gallery from extracted sprites",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path.cwd() / "extracted",
        help="Directory containing sprites/ (default: ./extracted)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress progress output",
    )

    args = parser.parse_args()

    result = generate_gallery(output_dir=args.output, verbose=not args.quiet)
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
    parser.add_argument(
        "-m",
        "--message",
        default="Update gallery",
        help="Commit message for gh-pages",
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
        print("Run 'pinacotheca-gallery' first to generate the gallery.", file=sys.stderr)
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


if __name__ == "__main__":
    main()
