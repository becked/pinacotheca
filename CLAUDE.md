# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Pinacotheca is a Python tool for extracting and cataloging sprite assets from the game **Old World** (a 4X strategy game by Mohawk Games). It uses UnityPy to extract sprites directly from Unity asset bundles without requiring external tools like AssetRipper.

## Commands

```bash
# Setup virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install UnityPy Pillow

# Extract sprites from Old World game assets
python extract_oldworld.py

# Regenerate the HTML gallery from already-extracted sprites
python generate_gallery.py
```

## Architecture

### Main Scripts

- **`extract_oldworld.py`**: Primary extraction script. Loads Unity assets from the game's Data directory, extracts all Sprite objects, categorizes them by name pattern (portraits, units, crests, etc.), and generates an HTML gallery.

- **`generate_gallery.py`**: Standalone gallery generator. Rebuilds `extracted/gallery.html` from existing sprites in `extracted/sprites/`.

- **`extract_assets.py`**: Earlier proof-of-concept that also extracts Texture2D assets. Less refined categorization.

### Key Design Patterns

- **Regex-based categorization**: The `CATEGORIES` dict maps category names to regex patterns. Patterns are checked in order—first match wins—so more specific patterns must precede general ones.

- **Platform detection**: Scripts auto-detect macOS vs Windows Steam installation paths for Old World.

- **Memory management**: Extraction uses `gc.collect()` every 500 sprites and explicitly deletes image data to handle the ~4000+ sprites without memory issues.

### Output Structure

```
extracted/
├── gallery.html      # Interactive HTML browser
└── sprites/
    ├── portraits/    # Character portraits by nation
    ├── units/        # Military unit icons
    ├── crests/       # Nation/family emblems
    └── ...           # ~30 categories total
```

## Category Regex Patterns

When adding new categories or refining existing ones, edit the `CATEGORIES` dict in `extract_oldworld.py`. Remember:
- Order matters: first matching pattern wins
- Use raw strings (r'...') for regex patterns
- The 'other' category is the catch-all at the end
