# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Pinacotheca is a Python tool for extracting and cataloging sprite assets from the game **Old World** (a 4X strategy game by Mohawk Games). It uses UnityPy to extract sprites directly from Unity asset bundles without requiring external tools like AssetRipper.

## Commands

```bash
# Setup virtual environment
python3 -m venv venv
source venv/bin/activate

# Install package with dev dependencies
pip install -e ".[dev]"

# Extract sprites from Old World game assets
pinacotheca

# Regenerate the HTML gallery from already-extracted sprites
pinacotheca-gallery

# Deploy gallery to GitHub Pages (gh-pages branch)
pinacotheca-deploy

# Run tests
pytest

# Run linter and formatter
ruff check .
ruff format .

# Run type checker
mypy src/
```

## Architecture

### Package Structure

```
src/pinacotheca/
├── __init__.py       # Package exports
├── categories.py     # Sprite categorization (regex patterns, pre-compiled)
├── extractor.py      # UnityPy extraction logic
├── gallery.py        # HTML gallery generator
├── cli.py            # Command-line interface entry points
└── py.typed          # PEP 561 marker for type hints
```

### Key Modules

- **`categories.py`**: Defines `CATEGORIES` dict mapping category names to regex patterns. Patterns are pre-compiled for performance. The `categorize()` function returns the category for a sprite name.

- **`extractor.py`**: Contains `extract_sprites()` which loads Unity assets, extracts Sprite objects, and saves them by category. Auto-detects game installation path on macOS and Windows.

- **`gallery.py`**: Contains `generate_gallery()` which builds an interactive HTML gallery with search and lightbox viewing.

- **`cli.py`**: Entry points for the three CLI commands: `pinacotheca`, `pinacotheca-gallery`, `pinacotheca-deploy`.

### Key Design Patterns

- **Regex-based categorization**: The `CATEGORIES` dict maps category names to regex patterns. Patterns are checked in order—first match wins—so more specific patterns must precede general ones. Patterns are pre-compiled at module load.

- **Platform detection**: `find_game_data()` auto-detects macOS vs Windows Steam installation paths for Old World.

- **Memory management**: Extraction uses `gc.collect()` every 500 sprites and explicitly deletes image data to handle the ~4000+ sprites without memory issues.

### Output Structure

```
extracted/
├── index.html        # Interactive HTML browser (for GitHub Pages)
├── gallery.html      # Same content (legacy compatibility)
└── sprites/
    ├── portraits/    # Character portraits by nation
    ├── units/        # Military unit icons
    ├── crests/       # Nation/family emblems
    └── ...           # ~40 categories total
```

## Testing

Tests are in `tests/test_categories.py` and cover the categorization regex patterns extensively (95 tests). Run with:

```bash
pytest -v
```

## Category Regex Patterns

When adding new categories or refining existing ones, edit the `CATEGORIES` dict in `src/pinacotheca/categories.py`. Remember:
- Order matters: first matching pattern wins
- Use raw strings (r'...') for regex patterns
- The 'other' category is the catch-all at the end
- Add corresponding display info to `CATEGORY_INFO`
- Add tests in `tests/test_categories.py`

## GitHub Pages Deployment

The gallery is deployed to the `gh-pages` branch using `ghp-import`. The workflow:

1. Run `pinacotheca` to extract sprites locally (requires game installed)
2. Run `pinacotheca-deploy` to push to `gh-pages` branch
3. GitHub Pages serves from `gh-pages` branch

Note: Only sprites (~500MB) are deployed, not textures (~2GB).
