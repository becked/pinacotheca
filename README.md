# Pinacotheca

*pin·a·co·the·ca* (n.) — An ancient Greek or Roman picture gallery.

[![CI](https://github.com/becked/pinacotheca/actions/workflows/ci.yml/badge.svg)](https://github.com/becked/pinacotheca/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

<img src="pinacotheca.jpg?v=2" width="600" alt="Pinacotheca">

A Python tool for extracting and cataloging sprite assets from **Old World** (the 4X strategy game by Mohawk Games). Uses [UnityPy](https://github.com/K0lb3/UnityPy) to extract sprites directly from Unity asset bundles—no external tools like AssetRipper needed.

**[Browse the Gallery](https://becked.github.io/pinacotheca/)**

## Features

- Pure Python extraction from Unity asset bundles
- Automatic categorization of 4000+ sprites into 40+ categories
- SvelteKit gallery with fuzzy search, filters, and lightbox viewing
- Cross-platform support (macOS and Windows)
- Memory-efficient processing for large asset files

## Requirements

- Python 3.11+
- Node.js 18+ (for building the web gallery)
- **Old World** installed via Steam (required for game assets)

## Installation

```bash
# Clone the repository
git clone https://github.com/becked/pinacotheca.git
cd pinacotheca

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install the package
pip install -e ".[dev]"
```

## Usage

### Extract Sprites

```bash
# Auto-detect game installation and extract to ./extracted
pinacotheca

# Specify output directory
pinacotheca -o ~/my-sprites

# Specify game data location manually
pinacotheca --game-data "/path/to/Old World/OldWorld_Data"
```

### Build the Gallery

After extracting sprites, build the SvelteKit gallery:

```bash
cd web
npm install   # First time only
npm run build
```

This outputs the gallery to `extracted/` alongside the sprites.

### Deploy to GitHub Pages

After building, deploy the gallery to GitHub Pages:

```bash
# Deploy to gh-pages branch
pinacotheca-deploy

# Preview without pushing
pinacotheca-deploy --dry-run
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run linter
ruff check .

# Run formatter
ruff format .

# Run type checker
mypy src/

# Install pre-commit hooks
pre-commit install
```

## Project Structure

```
pinacotheca/
├── src/pinacotheca/
│   ├── __init__.py       # Package exports
│   ├── categories.py     # Sprite categorization (regex patterns)
│   ├── extractor.py      # UnityPy extraction logic
│   ├── gallery.py        # Legacy HTML gallery generator
│   └── cli.py            # Command-line interface
├── web/                  # SvelteKit gallery (primary web interface)
│   ├── scripts/
│   │   └── generate-manifest.ts
│   ├── src/
│   │   ├── lib/          # Components, utils, types
│   │   └── routes/       # SvelteKit pages
│   └── svelte.config.js
├── tests/
│   └── test_categories.py
├── extracted/            # Output directory (git-ignored)
│   ├── index.html        # Gallery (built from web/)
│   └── sprites/          # Categorized sprite images
└── pyproject.toml        # Project configuration
```

## Sprite Categories

Sprites are automatically categorized by name patterns:

| Category | Description | Examples |
|----------|-------------|----------|
| `portraits` | Character portraits by nation | `ROME_MALE_01`, `EGYPT_LEADER_FEMALE_02` |
| `units` | Military unit icons | `UNIT_HOPLITE`, `UNIT_LEGION` |
| `crests` | Nation/family emblems | `CREST_ROME`, `CREST_JULIUS` |
| `improvements` | City improvements | `IMPROVEMENT_FARM`, `IMPROVEMENT_MINE` |
| `resources` | Resource icons | `RESOURCE_IRON`, `GOOD_WINE` |
| `techs` | Technology icons | `TECH_IRONWORKING` |
| ... | 40+ categories total | |

See [`categories.py`](src/pinacotheca/categories.py) for the full list of patterns.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgments

- [Mohawk Games](https://mohawkgames.com/) for creating Old World
- [UnityPy](https://github.com/K0lb3/UnityPy) for the Unity asset extraction library
