/**
 * Generate manifest.json from extracted sprites directory.
 * Scans ../extracted/sprites/ and reads image dimensions with sharp.
 *
 * Run with: npx tsx scripts/generate-manifest.ts
 */

import { readdir, writeFile, stat, readFile } from 'node:fs/promises';
import { join, basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import sharp from 'sharp';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
// Paths can be overridden via env vars for testing; defaults match the build layout.
const SPRITES_DIR =
	process.env.PINACOTHECA_SPRITES_DIR ?? join(__dirname, '../../extracted/sprites');
const SIDECAR_FILE =
	process.env.PINACOTHECA_SIDECAR_FILE ?? join(__dirname, '../../extracted/.gallery-filter.json');
const OUTPUT_FILE =
	process.env.PINACOTHECA_MANIFEST_FILE ?? join(__dirname, '../src/data/manifest.json');

// Mirrors gallery_filter.py's pattern contract: only `*` wildcards, no `?`,
// no `[...]`, no `**`. `*` does not match `/`. Parity is verified by
// tests/test_gallery_filter.py::test_python_ts_pattern_parity.
interface GalleryFilter {
	generatedAt: string;
	excludeGlobs: string[];
	reason: string;
}

async function loadFilter(): Promise<GalleryFilter> {
	try {
		const raw = await readFile(SIDECAR_FILE, 'utf-8');
		return JSON.parse(raw) as GalleryFilter;
	} catch {
		// Hard-fail when sprites/ exists but the sidecar doesn't — the whole
		// point of the filter is to enforce the gh-pages 1 GB cap. Don't
		// silently ship excluded composites.
		try {
			await stat(SPRITES_DIR);
			console.error(`ERROR: ${SIDECAR_FILE} not found, but ${SPRITES_DIR} exists.`);
			console.error('Run `pinacotheca` first to (re)generate the sidecar.');
			process.exit(1);
		} catch {
			// sprites/ also missing → fresh checkout, nothing to filter
			return { generatedAt: '', excludeGlobs: [], reason: '' };
		}
		throw new Error('unreachable');
	}
}

function globToRegExp(pattern: string): RegExp {
	const escaped = pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '[^/]*');
	return new RegExp(`^${escaped}$`);
}

// Mirror of Python CATEGORY_INFO - keep in sync with src/pinacotheca/categories.py
const CATEGORY_INFO: Record<string, { displayName: string; icon: string }> = {
	portraits: { displayName: 'Portraits', icon: '👤' },
	units: { displayName: 'Units', icon: '⚔️' },
	unit_actions: { displayName: 'Unit Actions', icon: '🎬' },
	unit_traits: { displayName: 'Unit Traits', icon: '🏅' },
	unit_effects: { displayName: 'Unit Effects', icon: '💫' },
	crests: { displayName: 'Crests & Emblems', icon: '🛡️' },
	gods: { displayName: 'Gods & Goddesses', icon: '✨' },
	religions: { displayName: 'Religions', icon: '🕯️' },
	improvements: { displayName: 'Improvements', icon: '🏛️' },
	resources: { displayName: 'Resources', icon: '💎' },
	yields: { displayName: 'Yields', icon: '📊' },
	techs: { displayName: 'Technologies', icon: '🔬' },
	laws: { displayName: 'Laws', icon: '📜' },
	traits: { displayName: 'Archetypes', icon: '🎭' },
	councils: { displayName: 'Councils', icon: '👥' },
	specialists: { displayName: 'Specialists', icon: '🎓' },
	missions: { displayName: 'Missions', icon: '🎯' },
	projects: { displayName: 'Projects', icon: '🔨' },
	terrains: { displayName: 'Terrains', icon: '🏔️' },
	vegetation: { displayName: 'Vegetation', icon: '🌳' },
	families: { displayName: 'Families', icon: '👨‍👩‍👧' },
	nations: { displayName: 'Nations', icon: '🏴' },
	theology: { displayName: 'Theologies', icon: '⛪' },
	wonders: { displayName: 'Wonders', icon: '🏛️' },
	bonuses: { displayName: 'Bonuses', icon: '⬆️' },
	cooldowns: { displayName: 'Cooldowns', icon: '⏱️' },
	achievements: { displayName: 'Achievements', icon: '🏆' },
	events_images: { displayName: 'UI', icon: '📰' },
	diplomacy: { displayName: 'Diplomacy', icon: '🤝' },
	city: { displayName: 'City', icon: '🏙️' },
	status: { displayName: 'Status Icons', icon: '📍' },
	effects: { displayName: 'Effects', icon: '✨' },
	character_select: { displayName: 'Character Select', icon: '👆' },
	tools: { displayName: 'Tools', icon: '🔧' },
	backgrounds: { displayName: 'Backgrounds', icon: '🖼️' },
	other: { displayName: 'Other', icon: '📁' }
};

interface Sprite {
	id: string;
	name: string;
	category: string;
	path: string;
	width: number;
	height: number;
	size: number;
	modSlug?: string;
	authors?: string[];
}

interface CategoryData {
	displayName: string;
	icon: string;
	count: number;
}

interface ModEntry {
	slug: string;
	displayName: string;
	author: string;
	version: string;
	description: string;
	disclaimer?: string;
	credit?: string[];
	count: number;
}

interface Manifest {
	generatedAt: string;
	totalSprites: number;
	categories: Record<string, CategoryData>;
	sprites: Sprite[];
	mods: ModEntry[];
}

async function getImageDimensions(filepath: string): Promise<{ width: number; height: number }> {
	try {
		const metadata = await sharp(filepath).metadata();
		return {
			width: metadata.width ?? 0,
			height: metadata.height ?? 0
		};
	} catch {
		console.warn(`Warning: Could not read dimensions for ${filepath}`);
		return { width: 0, height: 0 };
	}
}

async function scanCategory(
	categoryDir: string,
	categoryName: string,
	filterRegexes: RegExp[]
): Promise<{ sprites: Sprite[]; skipped: number }> {
	const sprites: Sprite[] = [];
	let skipped = 0;
	const files = await readdir(categoryDir);

	for (const file of files) {
		if (!file.endsWith('.png')) continue;

		const filepath = join(categoryDir, file);
		const fileStat = await stat(filepath);
		if (!fileStat.isFile()) continue;

		const relPath = `${categoryName}/${file}`;
		if (filterRegexes.some((re) => re.test(relPath))) {
			skipped++;
			continue;
		}

		const name = basename(file, '.png');
		const dimensions = await getImageDimensions(filepath);

		sprites.push({
			id: `${categoryName}/${name}`,
			name,
			category: categoryName,
			path: `sprites/${categoryName}/${file}`,
			width: dimensions.width,
			height: dimensions.height,
			size: fileStat.size
		});
	}

	return { sprites, skipped };
}

interface AttributionOverride {
	pattern: string;
	authors: string[];
}

interface AttributionTable {
	default: string[];
	overrides?: AttributionOverride[];
}

interface ModSidecar {
	slug: string;
	displayName: string;
	author: string;
	version: string;
	description: string;
	disclaimer?: string;
	credit?: string[];
	attribution?: AttributionTable;
}

/**
 * Resolve a sprite's author list against the mod's attribution table.
 * Tries each override pattern (anchored regex) against the sprite's
 * basename and returns the first match's authors; falls back to the
 * default list.
 */
function resolveAuthors(
	spriteName: string,
	attribution: AttributionTable | undefined,
	fallbackAuthor: string
): string[] {
	if (!attribution) {
		return fallbackAuthor ? [fallbackAuthor] : [];
	}
	for (const override of attribution.overrides ?? []) {
		try {
			const re = new RegExp(override.pattern);
			if (re.test(spriteName)) {
				return override.authors;
			}
		} catch {
			// Skip malformed regex; fall through to the default.
		}
	}
	return attribution.default;
}

/**
 * Walk ``sprites/mods/<slug>/<category>/*.png`` for every installed mod,
 * read each mod's ``mod.json`` sidecar, and emit sprites + a per-mod
 * record for attribution. Each mod sprite is tagged with ``modSlug``
 * and a ``category`` of ``mod:<slug>`` so the gallery can filter on
 * the mod axis while still grouping by its base-game sub-category
 * (units, improvements, sprites, ...).
 */
async function scanMods(
	modsDir: string,
	filterRegexes: RegExp[]
): Promise<{ sprites: Sprite[]; mods: ModEntry[]; skipped: number }> {
	const sprites: Sprite[] = [];
	const mods: ModEntry[] = [];
	let skipped = 0;
	let entries: string[] = [];
	try {
		entries = await readdir(modsDir);
	} catch {
		return { sprites, mods, skipped };
	}
	for (const slug of entries.sort()) {
		const modRoot = join(modsDir, slug);
		const modStat = await stat(modRoot);
		if (!modStat.isDirectory()) continue;
		let sidecar: ModSidecar | null = null;
		try {
			const raw = await readFile(join(modRoot, 'mod.json'), 'utf-8');
			sidecar = JSON.parse(raw) as ModSidecar;
		} catch {
			// A directory without mod.json isn't an extracted mod — skip.
			continue;
		}
		const subdirs = await readdir(modRoot);
		const modCategory = `mod:${slug}`;
		let count = 0;
		for (const sub of subdirs.sort()) {
			const subPath = join(modRoot, sub);
			const subStat = await stat(subPath);
			if (!subStat.isDirectory()) continue;
			const files = await readdir(subPath);
			for (const file of files) {
				if (!file.endsWith('.png')) continue;
				const filepath = join(subPath, file);
				const fileStat = await stat(filepath);
				if (!fileStat.isFile()) continue;
				const relPath = `mods/${slug}/${sub}/${file}`;
				if (filterRegexes.some((re) => re.test(relPath))) {
					skipped++;
					continue;
				}
				const name = basename(file, '.png');
				const dimensions = await getImageDimensions(filepath);
				const authors = resolveAuthors(name, sidecar.attribution, sidecar.author);
				sprites.push({
					id: `${modCategory}/${name}`,
					name,
					category: modCategory,
					path: `sprites/${relPath}`,
					width: dimensions.width,
					height: dimensions.height,
					size: fileStat.size,
					modSlug: slug,
					...(authors.length > 0 ? { authors } : {})
				});
				count++;
			}
		}
		if (count > 0) {
			mods.push({
				slug: sidecar.slug,
				displayName: sidecar.displayName,
				author: sidecar.author,
				version: sidecar.version,
				description: sidecar.description,
				count,
				...(sidecar.disclaimer ? { disclaimer: sidecar.disclaimer } : {}),
				...(sidecar.credit && sidecar.credit.length ? { credit: sidecar.credit } : {})
			});
		}
	}
	return { sprites, mods, skipped };
}

async function generateManifest(): Promise<void> {
	console.log('Generating manifest from:', SPRITES_DIR);

	// Check if sprites directory exists
	try {
		await stat(SPRITES_DIR);
	} catch {
		console.error('Error: Sprites directory not found:', SPRITES_DIR);
		console.error('Run `pinacotheca` first to extract sprites.');
		process.exit(1);
	}

	const filter = await loadFilter();
	const filterRegexes = filter.excludeGlobs.map(globToRegExp);
	if (filter.excludeGlobs.length > 0) {
		console.log(`Loaded gallery filter (${filter.excludeGlobs.length} pattern(s)):`);
		for (const g of filter.excludeGlobs) {
			console.log(`  - ${g}`);
		}
	}

	const categories = await readdir(SPRITES_DIR);
	const allSprites: Sprite[] = [];
	const categoryData: Record<string, CategoryData> = {};
	let mods: ModEntry[] = [];

	let processed = 0;
	let totalSkipped = 0;
	for (const category of categories.sort()) {
		const categoryDir = join(SPRITES_DIR, category);
		const categoryStat = await stat(categoryDir);
		if (!categoryStat.isDirectory()) continue;

		// `mods/` is laid out one level deeper than other categories:
		// `sprites/mods/<slug>/<sub>/*.png` instead of `sprites/<cat>/*.png`.
		// Handle it via a dedicated scanner that also reads per-mod
		// attribution sidecars.
		if (category === 'mods') {
			console.log('Processing mods...');
			const result = await scanMods(categoryDir, filterRegexes);
			mods = result.mods;
			allSprites.push(...result.sprites);
			totalSkipped += result.skipped;
			processed += result.sprites.length;
			console.log(
				`  Found ${result.mods.length} mod(s) contributing ${result.sprites.length} sprite(s)` +
					(result.skipped > 0 ? `, skipped ${result.skipped} via filter` : '')
			);
			continue;
		}

		console.log(`Processing ${category}...`);
		const { sprites, skipped } = await scanCategory(categoryDir, category, filterRegexes);
		totalSkipped += skipped;

		if (sprites.length > 0) {
			allSprites.push(...sprites);

			const info = CATEGORY_INFO[category] ?? {
				displayName: category.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
				icon: '📁'
			};

			categoryData[category] = {
				displayName: info.displayName,
				icon: info.icon,
				count: sprites.length
			};

			processed += sprites.length;
			console.log(
				`  Found ${sprites.length} sprites (total: ${processed})` +
					(skipped > 0 ? `, skipped ${skipped} via filter` : '')
			);
		} else if (skipped > 0) {
			console.log(`  Skipped ${skipped} sprites via filter`);
		}
	}

	// Sort sprites by category then name
	allSprites.sort((a, b) => {
		if (a.category !== b.category) {
			return a.category.localeCompare(b.category);
		}
		return a.name.localeCompare(b.name);
	});

	// Sort mod entries by display name for deterministic order in the gallery.
	mods.sort((a, b) => a.displayName.localeCompare(b.displayName));

	const manifest: Manifest = {
		generatedAt: new Date().toISOString(),
		totalSprites: allSprites.length,
		categories: categoryData,
		sprites: allSprites,
		mods
	};

	await writeFile(OUTPUT_FILE, JSON.stringify(manifest, null, '\t'));
	console.log(`\nManifest saved to: ${OUTPUT_FILE}`);
	console.log(`Total sprites: ${manifest.totalSprites}`);
	console.log(`Categories: ${Object.keys(categoryData).length}`);
	console.log(`Mods: ${manifest.mods.length}`);
	if (totalSkipped > 0) {
		console.log(`Excluded ${totalSkipped} sprites via gallery filter.`);
		console.log(`  Reason: ${filter.reason}`);
	}
}

generateManifest().catch(console.error);
