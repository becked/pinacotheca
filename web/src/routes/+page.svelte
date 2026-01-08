<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { browser } from '$app/environment';
	import { base } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
	import HomeView from '$lib/components/HomeView.svelte';
	import ResultsView from '$lib/components/ResultsView.svelte';
	import { getCategoryInfo } from '$lib/utils/categories';
	import { humanizeName } from '$lib/utils/humanize';
	import type { Sprite, FilterState } from '$lib/types';
	import manifest from '$lib/../../src/data/manifest.json';

	// Build searchable sprite list with humanized names
	interface SearchableSprite extends Sprite {
		displayName: string;
		searchText: string; // Combined lowercase text for searching
	}

	const searchableSprites: SearchableSprite[] = (manifest.sprites as Sprite[]).map((s) => {
		const displayName = humanizeName(s.name);
		return {
			...s,
			displayName,
			// Combine name and displayName, normalize for searching
			searchText: `${s.name} ${displayName}`.toLowerCase().replace(/[_-]/g, ' ')
		};
	});

	// Filter state
	let filters = $state<FilterState>({
		query: '',
		category: null,
		minWidth: null,
		maxWidth: null,
		minHeight: null,
		maxHeight: null,
		aspectRatio: 'all'
	});

	// Lightbox state
	let lightboxSprite = $state<Sprite | null>(null);

	// Determine if we're in results view (has search or category filter)
	let isResultsView = $derived(
		filters.query !== '' || filters.category !== null
	);

	// Sync state from URL (reactive to handle browser back/forward)
	$effect(() => {
		const url = $page.url;
		filters.query = url.searchParams.get('q') ?? '';
		filters.category = url.searchParams.get('cat');
		filters.minWidth = url.searchParams.has('minW') ? Number(url.searchParams.get('minW')) : null;
		filters.maxWidth = url.searchParams.has('maxW') ? Number(url.searchParams.get('maxW')) : null;
		filters.minHeight = url.searchParams.has('minH') ? Number(url.searchParams.get('minH')) : null;
		filters.maxHeight = url.searchParams.has('maxH') ? Number(url.searchParams.get('maxH')) : null;
		const ar = url.searchParams.get('ar');
		if (ar === 'square' || ar === 'portrait' || ar === 'landscape') {
			filters.aspectRatio = ar;
		} else {
			filters.aspectRatio = 'all';
		}
		const spriteId = url.searchParams.get('sprite');
		if (spriteId) {
			const sprite = (manifest.sprites as Sprite[]).find((s) => s.id === spriteId);
			lightboxSprite = sprite ?? null;
		} else {
			lightboxSprite = null;
		}
	});

	// Sync state to URL
	function updateUrl(replace = false) {
		if (!browser) return;
		const params = new URLSearchParams();
		if (filters.query) params.set('q', filters.query);
		if (filters.category) params.set('cat', filters.category);
		if (filters.minWidth) params.set('minW', String(filters.minWidth));
		if (filters.maxWidth) params.set('maxW', String(filters.maxWidth));
		if (filters.minHeight) params.set('minH', String(filters.minHeight));
		if (filters.maxHeight) params.set('maxH', String(filters.maxHeight));
		if (filters.aspectRatio !== 'all') params.set('ar', filters.aspectRatio);
		if (lightboxSprite) params.set('sprite', lightboxSprite.id);

		const newUrl = params.toString() ? `${base}/?${params}` : `${base}/`;
		goto(newUrl, { replaceState: replace, noScroll: true, keepFocus: true });
	}

	// Apply all filters except category (for computing per-category counts)
	let spritesBeforeCategoryFilter = $derived.by(() => {
		let result: SearchableSprite[];

		// Filter by search query using substring matching
		if (filters.query) {
			// Normalize query: lowercase, replace separators with spaces, split into terms
			const queryTerms = filters.query
				.toLowerCase()
				.replace(/[_-]/g, ' ')
				.split(/\s+/)
				.filter((term) => term.length > 0);

			// Match sprites that contain ALL query terms (AND search)
			result = searchableSprites.filter((s) =>
				queryTerms.every((term) => s.searchText.includes(term))
			);
		} else {
			result = searchableSprites;
		}

		// Filter by dimensions
		if (filters.minWidth) {
			result = result.filter((s) => s.width >= filters.minWidth!);
		}
		if (filters.maxWidth) {
			result = result.filter((s) => s.width <= filters.maxWidth!);
		}
		if (filters.minHeight) {
			result = result.filter((s) => s.height >= filters.minHeight!);
		}
		if (filters.maxHeight) {
			result = result.filter((s) => s.height <= filters.maxHeight!);
		}

		// Filter by aspect ratio
		if (filters.aspectRatio !== 'all') {
			result = result.filter((s) => {
				const ratio = s.width / s.height;
				if (filters.aspectRatio === 'square') return ratio >= 0.9 && ratio <= 1.1;
				if (filters.aspectRatio === 'portrait') return ratio < 0.9;
				if (filters.aspectRatio === 'landscape') return ratio > 1.1;
				return true;
			});
		}

		return result;
	});

	// Filter sprites based on current filters (including category)
	let filteredSprites = $derived.by(() => {
		let result = spritesBeforeCategoryFilter;

		// Filter by category
		if (filters.category) {
			result = result.filter((s) => s.category === filters.category);
		}

		return result;
	});

	// Compute category counts from filtered sprites (before category filter)
	let filteredCategories = $derived.by(() => {
		const counts: Record<string, number> = {};
		for (const sprite of spritesBeforeCategoryFilter) {
			counts[sprite.category] = (counts[sprite.category] || 0) + 1;
		}

		// Build new categories object with filtered counts
		const result: Record<string, import('$lib/types').CategoryData> = {};
		for (const [cat, data] of Object.entries(manifest.categories)) {
			result[cat] = {
				...data,
				count: counts[cat] || 0
			};
		}
		return result;
	});

	function handleSearch(query: string) {
		filters.query = query;
		updateUrl(true); // Replace for typing
	}

	function handleCategorySelect(category: string | null) {
		filters.category = category;
		updateUrl(); // Push for navigation
	}

	function handleSpriteClick(sprite: Sprite) {
		lightboxSprite = sprite;
		updateUrl(); // Push for navigation
	}

	function closeLightbox() {
		lightboxSprite = null;
		updateUrl(); // Push for navigation
	}

	function downloadSprite() {
		if (!lightboxSprite) return;
		const link = document.createElement('a');
		link.href = lightboxSprite.path;
		link.download = `${lightboxSprite.name}.png`;
		link.click();
	}

	function handleDimensionChange(field: 'minWidth' | 'maxWidth' | 'minHeight' | 'maxHeight', value: string) {
		const num = value ? parseInt(value, 10) : null;
		filters[field] = num && !isNaN(num) ? num : null;
		updateUrl(true); // Replace for filter tweaks
	}

	function handleAspectRatioChange(value: FilterState['aspectRatio']) {
		filters.aspectRatio = value;
		updateUrl(true); // Replace for filter tweaks
	}

	function clearDimensionFilters() {
		filters.minWidth = null;
		filters.maxWidth = null;
		filters.minHeight = null;
		filters.maxHeight = null;
		filters.aspectRatio = 'all';
		updateUrl(true); // Replace for filter tweaks
	}

	function clearAllFilters() {
		filters.query = '';
		filters.category = null;
		filters.minWidth = null;
		filters.maxWidth = null;
		filters.minHeight = null;
		filters.maxHeight = null;
		filters.aspectRatio = 'all';
		updateUrl(); // Push for navigation
	}

	// Keyboard navigation
	function handleKeydown(e: KeyboardEvent) {
		if (!lightboxSprite) return;

		if (e.key === 'Escape') {
			closeLightbox();
		} else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
			const currentIndex = filteredSprites.findIndex((s) => s.id === lightboxSprite?.id);
			if (currentIndex === -1) return;

			const newIndex =
				e.key === 'ArrowLeft'
					? (currentIndex - 1 + filteredSprites.length) % filteredSprites.length
					: (currentIndex + 1) % filteredSprites.length;

			lightboxSprite = filteredSprites[newIndex];
			updateUrl(true); // Replace for arrow navigation
		}
	}

	// Format file size for lightbox
	function formatFileSize(bytes: number | undefined): string {
		if (!bytes) return '';
		const kb = bytes / 1024;
		return kb < 10 ? `${kb.toFixed(1)} KB` : `${Math.round(kb)} KB`;
	}
</script>

<svelte:window onkeydown={handleKeydown} />

<div class="min-h-screen bg-background">
	{#if isResultsView}
		<ResultsView
			sprites={filteredSprites}
			categories={filteredCategories}
			{filters}
			onSearch={handleSearch}
			onCategoryChange={handleCategorySelect}
			onClearAll={clearAllFilters}
			onSpriteClick={handleSpriteClick}
		/>
	{:else}
		<HomeView
			categories={manifest.categories}
			sprites={manifest.sprites as Sprite[]}
			searchQuery={filters.query}
			onSearch={handleSearch}
			onCategorySelect={(cat) => handleCategorySelect(cat)}
		/>
	{/if}
</div>

<!-- Lightbox -->
{#if lightboxSprite}
	{@const categoryInfo = getCategoryInfo(lightboxSprite.category)}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/95"
		onclick={closeLightbox}
		onkeydown={(e) => e.key === 'Enter' && closeLightbox()}
		role="dialog"
		aria-modal="true"
		tabindex="-1"
	>
		<button
			class="absolute right-6 top-6 text-3xl text-white hover:text-primary"
			onclick={closeLightbox}
			aria-label="Close"
		>
			&times;
		</button>

		<div
			class="flex flex-col items-center"
			onclick={(e) => e.stopPropagation()}
			onkeydown={(e) => e.stopPropagation()}
			role="presentation"
		>
			<img
				src={lightboxSprite.path}
				alt={lightboxSprite.name}
				class="sprite-image max-h-[70vh] max-w-[90vw] object-contain"
			/>
			<div class="mt-6 text-center">
				<p class="text-xl text-foreground">{humanizeName(lightboxSprite.name)}</p>
				<p class="mt-1 text-xs text-muted/70 font-mono">{lightboxSprite.name}</p>
				<p class="mt-1 text-sm text-muted">
					{categoryInfo.icon}
					{categoryInfo.displayName}
					&bull;
					{lightboxSprite.width} &times; {lightboxSprite.height}px
					{#if lightboxSprite.size}
						&bull;
						{formatFileSize(lightboxSprite.size)}
					{/if}
				</p>
				<Button class="mt-4" onclick={downloadSprite}>
					Download
				</Button>
			</div>
		</div>

		<div class="absolute bottom-6 left-1/2 -translate-x-1/2 text-sm text-muted">
			Use arrow keys to navigate &bull; Press Escape to close
		</div>
	</div>
{/if}
