export interface Sprite {
	id: string;
	name: string;
	category: string;
	path: string;
	width: number;
	height: number;
	size: number;
}

export interface CategoryData {
	displayName: string;
	icon: string;
	count: number;
}

export interface Manifest {
	generatedAt: string;
	totalSprites: number;
	categories: Record<string, CategoryData>;
	sprites: Sprite[];
}

export interface FilterState {
	query: string;
	category: string | null;
	minWidth: number | null;
	maxWidth: number | null;
	minHeight: number | null;
	maxHeight: number | null;
	aspectRatio: 'all' | 'square' | 'portrait' | 'landscape';
}

export const DEFAULT_FILTER_STATE: FilterState = {
	query: '',
	category: null,
	minWidth: null,
	maxWidth: null,
	minHeight: null,
	maxHeight: null,
	aspectRatio: 'all'
};
