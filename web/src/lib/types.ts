export interface Sprite {
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

export interface CategoryData {
	displayName: string;
	icon: string;
	count: number;
}

export interface ModEntry {
	slug: string;
	displayName: string;
	author: string;
	version: string;
	description: string;
	disclaimer?: string;
	credit?: string[];
	count: number;
}

export interface Manifest {
	generatedAt: string;
	totalSprites: number;
	categories: Record<string, CategoryData>;
	sprites: Sprite[];
	mods: ModEntry[];
}

export interface FilterState {
	query: string;
	category: string | null;
	mod: string | null;
	includeMods: boolean;
	minWidth: number | null;
	maxWidth: number | null;
	minHeight: number | null;
	maxHeight: number | null;
	aspectRatio: 'all' | 'square' | 'portrait' | 'landscape';
}

export const DEFAULT_FILTER_STATE: FilterState = {
	query: '',
	category: null,
	mod: null,
	includeMods: false,
	minWidth: null,
	maxWidth: null,
	minHeight: null,
	maxHeight: null,
	aspectRatio: 'all'
};
