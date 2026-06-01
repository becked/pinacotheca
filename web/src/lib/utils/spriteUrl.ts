import { dev } from '$app/environment';

/**
 * Resolve the image URL for a sprite.
 *
 * The local `extracted/sprites/` tree (and `manifest.json`) stores `.png` —
 * that's what the dev server and our sister tool per-ankh consume. The deployed
 * gh-pages gallery ships WebP instead (converted at deploy time by
 * `pinacotheca-deploy`), which keeps the site comfortably under GitHub Pages'
 * 1 GB cap. So in production we swap the extension to `.webp`; in dev we keep
 * `.png` (the local files are still PNG).
 *
 * Keep this in sync with the conversion in `src/pinacotheca/cli.py`
 * (`_convert_to_webp`) and the download filename in `+page.svelte`.
 */
export const SPRITE_EXT = dev ? 'png' : 'webp';

export function spriteSrc(sprite: { path: string }): string {
	return dev ? sprite.path : sprite.path.replace(/\.png$/, '.webp');
}
