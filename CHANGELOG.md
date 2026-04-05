# Changelog

## [Unreleased]

## [1.1.0] - 2026-04-05

- Clean up versioning, deployment, and CLI commands
- Add `pinacotheca-web` and `pinacotheca-web-build` CLI commands
- Decouple legacy HTML gallery from extraction pipeline
- Single-source version from `pyproject.toml` via `importlib.metadata`
- Remove redundant GitHub Actions deploy workflow
- Add version bump script and changelog

## [1.0.0] - 2025-01-01

Initial release.

- Extract sprites from Old World Unity asset bundles via UnityPy
- Regex-based categorization into ~40 categories
- 3D unit mesh rendering to 2D images
- SvelteKit gallery with search, filters, and lightbox
- Legacy standalone HTML gallery
- Texture atlas generation for map rendering
- Exclusion pattern support for sprite filtering
- GitHub Pages deployment via `pinacotheca-deploy`
- CI pipeline with ruff, mypy, and pytest
