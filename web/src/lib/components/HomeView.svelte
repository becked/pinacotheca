<script lang="ts">
	import { base } from '$app/paths';
	import type { CategoryData, ModEntry, Sprite } from '$lib/types';
	import CategoryCard from './CategoryCard.svelte';
	import ModCard from './ModCard.svelte';

	interface Props {
		categories: Record<string, CategoryData>;
		mods: ModEntry[];
		sprites: Sprite[];
		searchQuery: string;
		onSearch: (query: string) => void;
		onCategorySelect: (category: string) => void;
		onModSelect: (slug: string) => void;
	}

	let { categories, mods, sprites, searchQuery, onSearch, onCategorySelect, onModSelect }: Props = $props();

	let categoryRepresentatives = $derived.by(() => {
		const reps: Record<string, Sprite | undefined> = {};
		for (const category of Object.keys(categories)) {
			reps[category] = sprites.find((s) => s.category === category && !s.modSlug);
		}
		return reps;
	});

	let modRepresentatives = $derived.by(() => {
		// Prefer the largest sprite per mod so mod cards display a visually
		// substantive thumbnail (a 3D unit render rather than a 63px icon).
		const reps: Record<string, Sprite | undefined> = {};
		for (const mod of mods) {
			let best: Sprite | undefined;
			let bestArea = 0;
			for (const s of sprites) {
				if (s.modSlug !== mod.slug) continue;
				const area = s.width * s.height;
				if (area > bestArea) {
					best = s;
					bestArea = area;
				}
			}
			reps[mod.slug] = best;
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
				autofocus
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

{#if mods.length > 0}
	<!-- Mods Section -->
	<section style="background-color: var(--color-surface); margin-top: 16px; width: 90%; margin-left: auto; margin-right: auto;">
		<div style="padding: 2rem 3rem 1rem 3rem;">
			<h2 style="font-size: 1.5rem; font-weight: 600; color: var(--color-foreground); margin: 0;">
				Mods
			</h2>
			<p style="font-size: 0.875rem; color: var(--color-muted); margin: 0.25rem 0 0 0;">
				Community-created art for Old World. Attribution sits next to each entry.
			</p>
		</div>
		<div style="padding: 0 3rem 3rem 3rem;">
			<div class="category-grid">
				{#each mods as mod (mod.slug)}
					<ModCard
						{mod}
						representativeSprite={modRepresentatives[mod.slug]}
						onclick={() => onModSelect(mod.slug)}
					/>
				{/each}
			</div>
		</div>
	</section>
{/if}

<style lang="postcss">
	@reference "tailwindcss";
	.category-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
		gap: 1.5rem;
	}
</style>
