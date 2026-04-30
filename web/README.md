# sv

Everything you need to build a Svelte project, powered by [`sv`](https://github.com/sveltejs/cli).

## Creating a project

If you're seeing this, you've probably already done this step. Congrats!

```sh
# create a new project in the current directory
npx sv create

# create a new project in my-app
npx sv create my-app
```

## Developing

Once you've created a project and installed dependencies with `npm install` (or `pnpm install` or `yarn`), start a development server:

```sh
npm run dev

# or start the server and open the app in a new browser tab
npm run dev -- --open
```

## Building

To create a production version of your app:

```sh
npm run build
```

You can preview the production build with `npm run preview`.

> To deploy your app, you may need to install an [adapter](https://svelte.dev/docs/kit/adapters) for your target environment.

## Gallery deploy filter

The build-time manifest generator (`scripts/generate-manifest.ts`) reads
`extracted/.gallery-filter.json` (written by the Python `pinacotheca` extractor)
and excludes matching files from the manifest. Currently the gallery does NOT
display per-(improvement, nation) urban composites (`*_URBAN.png`) — they live
locally in `extracted/sprites/improvements/` for use by per-ankh, our sister
hex-map renderer, but are too large to ship within GitHub Pages' 1 GB site cap.

The script fails hard if `extracted/sprites/` exists but the sidecar doesn't —
run `pinacotheca` (from the repo root) to regenerate it. Filter list and
design details live in `../src/pinacotheca/gallery_filter.py` and the project
root `CLAUDE.md`.
