<script lang="ts">
	import { base } from '$app/paths';
	import type { CategoryData, Sprite } from '$lib/types';
	import CategoryCard from './CategoryCard.svelte';

	interface Props {
		categories: Record<string, CategoryData>;
		sprites: Sprite[];
		searchQuery: string;
		onSearch: (query: string) => void;
		onCategorySelect: (category: string) => void;
	}

	let { categories, sprites, searchQuery, onSearch, onCategorySelect }: Props = $props();

	let categoryRepresentatives = $derived.by(() => {
		const reps: Record<string, Sprite | undefined> = {};
		for (const category of Object.keys(categories)) {
			reps[category] = sprites.find((s) => s.category === category);
		}
		return reps;
	});

	let sortedCategories = $derived(
		Object.entries(categories).sort((a, b) =>
			a[1].displayName.localeCompare(b[1].displayName)
		)
	);

	let totalSprites = $derived(
		Object.values(categories).reduce((sum, cat) => sum + cat.count, 0)
	);

	function handleKeyDown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			const value = (e.target as HTMLInputElement).value;
			if (value.trim()) {
				onSearch(value);
			}
		}
	}

	function handleSearchClick() {
		if (searchQuery.trim()) {
			onSearch(searchQuery);
		}
	}
</script>

<!-- Header Section - Brown -->
<header style="background-color: var(--color-surface);">
	<div style="max-width: 1024px; margin: 0 auto; padding: 1.5rem; display: flex; align-items: center; justify-content: center; gap: 1.5rem;">
		<a href="{base}/" style="display: flex; align-items: center; gap: 1.5rem; text-decoration: none;">
			<img src="{base}/pinacotheca.jpg" alt="Pinacotheca" style="height: 4rem; width: auto;" />
			<h1 style="font-size: 4rem; font-weight: bold; letter-spacing: -0.025em; color: var(--color-foreground);">
				Pinacotheca
			</h1>
		</a>
	</div>
</header>

<!-- Search Section - Brown -->
<section style="background-color: var(--color-surface); margin-top: 16px; width: 90%; margin-left: auto; margin-right: auto;">
	<div style="max-width: 800px; margin: 0 auto; padding: 2rem 1.5rem;">
		<div style="position: relative;">
			<input
				type="text"
				placeholder="Search"
				value={searchQuery}
				oninput={(e) => (searchQuery = (e.target as HTMLInputElement).value)}
				onkeydown={handleKeyDown}
				style="width: 100%; padding: 1rem 1.5rem; padding-right: 3rem; font-size: 1.125rem; border: 2px solid var(--color-border); border-radius: 0.5rem; background-color: var(--color-background); color: var(--color-foreground);"
			/>
			{#if searchQuery}
				<button
					type="button"
					onclick={() => { searchQuery = ''; onSearch(''); }}
					aria-label="Clear search"
					style="position: absolute; right: 0.75rem; top: 50%; transform: translateY(-50%); background: none; border: none; cursor: pointer; padding: 0.5rem; color: var(--color-muted); font-size: 1.25rem; line-height: 1;"
				>
					&times;
				</button>
			{/if}
		</div>
	</div>
</section>

<!-- Gallery Section - Brown -->
<section style="background-color: var(--color-surface); margin-top: 16px; width: 90%; margin-left: auto; margin-right: auto;">
	<div style="padding: 3rem;">
		<div class="category-grid">
			{#each sortedCategories as [category, data]}
				<CategoryCard
					{category}
					categoryData={data}
					representativeSprite={categoryRepresentatives[category]}
					onclick={() => onCategorySelect(category)}
				/>
			{/each}
		</div>
	</div>
</section>

<style lang="postcss">
	@reference "tailwindcss";
	.category-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
		gap: 1.5rem;
	}
</style>
