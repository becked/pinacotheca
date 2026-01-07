<script lang="ts">
	import type { Sprite, CategoryData, FilterState } from '$lib/types';
	import SpriteCard from './SpriteCard.svelte';
	import { getCategoryInfo } from '$lib/utils/categories';

	interface Props {
		sprites: Sprite[];
		categories: Record<string, CategoryData>;
		filters: FilterState;
		onSearch: (query: string) => void;
		onCategoryChange: (category: string | null) => void;
		onClearAll: () => void;
		onSpriteClick: (sprite: Sprite) => void;
	}

	let {
		sprites,
		categories,
		filters,
		onSearch,
		onCategoryChange,
		onClearAll,
		onSpriteClick
	}: Props = $props();

	let resultSummary = $derived.by(() => {
		const count = sprites.length.toLocaleString();
		if (filters.query && filters.category) {
			const catInfo = getCategoryInfo(filters.category);
			return `${count} results for "${filters.query}" in ${catInfo.displayName}`;
		}
		if (filters.query) {
			return `${count} results for "${filters.query}"`;
		}
		if (filters.category) {
			const catInfo = getCategoryInfo(filters.category);
			return `${count} sprites in ${catInfo.displayName}`;
		}
		return `${count} sprites`;
	});

	let sortedCategories = $derived(
		Object.entries(categories).sort((a, b) =>
			a[1].displayName.localeCompare(b[1].displayName)
		)
	);

	function handleKeyDown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			onSearch((e.target as HTMLInputElement).value);
		}
	}
</script>

<!-- Header Section - Brown -->
<header style="background-color: #241f1c;">
	<div style="max-width: 1024px; margin: 0 auto; padding: 1.5rem; display: flex; align-items: center; justify-content: center; gap: 1.5rem;">
		<img src="/pinacotheca.jpg" alt="Pinacotheca" style="height: 4rem; width: auto;" />
		<h1 style="font-size: 4rem; font-weight: bold; letter-spacing: -0.025em; color: #e8dcd4;">
			Pinacotheca
		</h1>
	</div>
</header>

<!-- Search Section - Brown -->
<section style="background-color: #241f1c; margin-top: 16px; width: 90%; margin-left: auto; margin-right: auto;">
	<div style="max-width: 800px; margin: 0 auto; padding: 2rem 1.5rem;">
		<input
			type="text"
			placeholder="Search"
			value={filters.query}
			oninput={(e) => onSearch((e.target as HTMLInputElement).value)}
			onkeydown={handleKeyDown}
			style="width: 100%; padding: 1rem 1.5rem; font-size: 1.125rem; border: 2px solid #3d3330; border-radius: 0.5rem; background-color: #0a0a0a; color: #e8dcd4;"
		/>
	</div>
</section>

<!-- Filter/Nav Section - Brown -->
<section style="background-color: #241f1c; margin-top: 16px; width: 90%; margin-left: auto; margin-right: auto;">
	<div style="max-width: 800px; margin: 0 auto; padding: 1rem 1.5rem; display: flex; align-items: center; gap: 1rem; flex-wrap: wrap;">
		<button
			onclick={onClearAll}
			style="color: #c17f59; background: none; border: none; cursor: pointer; font-size: 0.875rem;"
		>
			&larr; Back to Browse
		</button>
		<span style="color: #7a6f68;">|</span>
		<select
			value={filters.category ?? ''}
			onchange={(e) => onCategoryChange((e.target as HTMLSelectElement).value || null)}
			style="padding: 0.5rem 1rem; border: 1px solid #3d3330; border-radius: 0.375rem; background-color: #0a0a0a; color: #e8dcd4; font-size: 0.875rem;"
		>
			<option value="">All Categories</option>
			{#each sortedCategories as [cat, data]}
				<option value={cat}>{data.displayName} ({data.count})</option>
			{/each}
		</select>
		<span style="color: #7a6f68; margin-left: auto; font-size: 0.875rem;">{resultSummary}</span>
	</div>
</section>

<!-- Results Section - Brown, 90% width -->
<section style="background-color: #241f1c; margin-top: 16px; width: 90%; margin-left: auto; margin-right: auto;">
	<div style="padding: 3rem;">
		{#if sprites.length > 0}
			<div class="results-grid">
				{#each sprites as sprite (sprite.id)}
					<SpriteCard {sprite} onclick={() => onSpriteClick(sprite)} />
				{/each}
			</div>
		{:else}
			<div style="text-align: center; padding: 4rem 0; color: #7a6f68;">
				<p style="font-size: 1.125rem;">No sprites found</p>
				<p style="margin-top: 0.5rem; font-size: 0.875rem;">Try adjusting your search or filters</p>
			</div>
		{/if}
	</div>
</section>

<style lang="postcss">
	@reference "tailwindcss";
	.results-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
		gap: 1.5rem;
	}
</style>
