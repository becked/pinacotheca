<script lang="ts">
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
			value={searchQuery}
			oninput={(e) => (searchQuery = (e.target as HTMLInputElement).value)}
			onkeydown={handleKeyDown}
			style="width: 100%; padding: 1rem 1.5rem; font-size: 1.125rem; border: 2px solid #3d3330; border-radius: 0.5rem; background-color: #0a0a0a; color: #e8dcd4;"
		/>
	</div>
</section>

<!-- Gallery Section - Brown -->
<section style="background-color: #241f1c; margin-top: 16px; width: 90%; margin-left: auto; margin-right: auto;">
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
