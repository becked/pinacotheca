/**
 * Generate manifest.json from extracted sprites directory.
 * Scans ../extracted/sprites/ and reads image dimensions with sharp.
 *
 * Run with: npx tsx scripts/generate-manifest.ts
 */

import { readdir, writeFile, stat } from 'node:fs/promises';
import { join, basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import sharp from 'sharp';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const SPRITES_DIR = join(__dirname, '../../extracted/sprites');
const OUTPUT_FILE = join(__dirname, '../src/data/manifest.json');

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
}

interface CategoryData {
	displayName: string;
	icon: string;
	count: number;
}

interface Manifest {
	generatedAt: string;
	totalSprites: number;
	categories: Record<string, CategoryData>;
	sprites: Sprite[];
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

async function scanCategory(categoryDir: string, categoryName: string): Promise<Sprite[]> {
	const sprites: Sprite[] = [];
	const files = await readdir(categoryDir);

	for (const file of files) {
		if (!file.endsWith('.png')) continue;

		const filepath = join(categoryDir, file);
		const fileStat = await stat(filepath);
		if (!fileStat.isFile()) continue;

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

	return sprites;
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

	const categories = await readdir(SPRITES_DIR);
	const allSprites: Sprite[] = [];
	const categoryData: Record<string, CategoryData> = {};

	let processed = 0;
	for (const category of categories.sort()) {
		const categoryDir = join(SPRITES_DIR, category);
		const categoryStat = await stat(categoryDir);
		if (!categoryStat.isDirectory()) continue;

		console.log(`Processing ${category}...`);
		const sprites = await scanCategory(categoryDir, category);

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
			console.log(`  Found ${sprites.length} sprites (total: ${processed})`);
		}
	}

	// Sort sprites by category then name
	allSprites.sort((a, b) => {
		if (a.category !== b.category) {
			return a.category.localeCompare(b.category);
		}
		return a.name.localeCompare(b.name);
	});

	const manifest: Manifest = {
		generatedAt: new Date().toISOString(),
		totalSprites: allSprites.length,
		categories: categoryData,
		sprites: allSprites
	};

	await writeFile(OUTPUT_FILE, JSON.stringify(manifest, null, '\t'));
	console.log(`\nManifest saved to: ${OUTPUT_FILE}`);
	console.log(`Total sprites: ${manifest.totalSprites}`);
	console.log(`Categories: ${Object.keys(categoryData).length}`);
}

generateManifest().catch(console.error);
