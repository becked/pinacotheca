<script lang="ts">
	import type { CategoryData, FilterState } from '$lib/types';

	interface Props {
		filters: FilterState;
		categories: Record<string, CategoryData>;
		onCategoryChange: (category: string | null) => void;
		onDimensionChange: (field: 'minWidth' | 'maxWidth' | 'minHeight' | 'maxHeight', value: string) => void;
		onAspectRatioChange: (value: FilterState['aspectRatio']) => void;
		onClearFilters: () => void;
	}

	let {
		filters,
		categories,
		onCategoryChange,
		onDimensionChange,
		onAspectRatioChange,
		onClearFilters
	}: Props = $props();

	let showFilters = $state(false);

	// Sort categories by display name for the dropdown
	let sortedCategories = $derived(
		Object.entries(categories).sort((a, b) =>
			a[1].displayName.localeCompare(b[1].displayName)
		)
	);

	// Check if any dimension filters are active
	let hasDimensionFilters = $derived(
		filters.minWidth !== null ||
		filters.maxWidth !== null ||
		filters.minHeight !== null ||
		filters.maxHeight !== null ||
		filters.aspectRatio !== 'all'
	);
</script>

<div class="border-b border-border bg-surface/50 py-4">
	<div class="filter-container flex flex-wrap items-center gap-4">
		<!-- Category Dropdown -->
		<div class="flex items-center gap-2">
			<label for="category-select" class="text-sm text-muted">Category:</label>
			<select
				id="category-select"
				class="h-10 rounded-lg border border-border bg-surface px-3 text-sm text-foreground focus:border-primary focus:outline-none"
				value={filters.category ?? ''}
				onchange={(e) => {
					const value = (e.target as HTMLSelectElement).value;
					onCategoryChange(value || null);
				}}
			>
				<option value="">All Categories</option>
				{#each sortedCategories as [category, data]}
					<option value={category}>{data.icon} {data.displayName} ({data.count})</option>
				{/each}
			</select>
		</div>

		<!-- Filters Toggle -->
		<button
			class="flex items-center gap-2 rounded-lg border border-border px-4 py-2 text-sm text-muted transition-colors hover:border-primary hover:text-foreground"
			class:border-primary={showFilters || hasDimensionFilters}
			class:text-foreground={showFilters || hasDimensionFilters}
			onclick={() => (showFilters = !showFilters)}
		>
			<span>Filters</span>
			{#if hasDimensionFilters}
				<span class="rounded bg-primary px-1.5 py-0.5 text-xs text-background">Active</span>
			{/if}
			<svg
				class="h-4 w-4 transition-transform"
				class:rotate-180={showFilters}
				fill="none"
				stroke="currentColor"
				viewBox="0 0 24 24"
			>
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
			</svg>
		</button>

		<!-- Clear All -->
		{#if filters.category || hasDimensionFilters}
			<button
				class="text-sm text-primary hover:text-primary-hover hover:underline"
				onclick={onClearFilters}
			>
				Clear all
			</button>
		{/if}
	</div>

	<!-- Expanded Filters -->
	{#if showFilters}
		<div class="filter-container mt-4 flex flex-wrap items-center gap-6 border-t border-border pt-4">
			<!-- Aspect Ratio -->
			<div class="flex items-center gap-2">
				<label for="aspect-ratio" class="text-sm text-muted">Shape:</label>
				<select
					id="aspect-ratio"
					class="h-9 rounded-lg border border-border bg-surface px-3 text-sm text-foreground focus:border-primary focus:outline-none"
					value={filters.aspectRatio}
					onchange={(e) => onAspectRatioChange((e.target as HTMLSelectElement).value as FilterState['aspectRatio'])}
				>
					<option value="all">All</option>
					<option value="square">Square</option>
					<option value="portrait">Portrait</option>
					<option value="landscape">Landscape</option>
				</select>
			</div>

			<!-- Width Range -->
			<div class="flex items-center gap-2">
				<label for="min-width" class="text-sm text-muted">Width:</label>
				<input
					id="min-width"
					type="number"
					placeholder="Min"
					class="h-9 w-20 rounded-lg border border-border bg-surface px-3 text-sm text-foreground focus:border-primary focus:outline-none"
					value={filters.minWidth ?? ''}
					oninput={(e) => onDimensionChange('minWidth', (e.target as HTMLInputElement).value)}
				/>
				<span class="text-muted">-</span>
				<input
					id="max-width"
					type="number"
					placeholder="Max"
					aria-label="Maximum width"
					class="h-9 w-20 rounded-lg border border-border bg-surface px-3 text-sm text-foreground focus:border-primary focus:outline-none"
					value={filters.maxWidth ?? ''}
					oninput={(e) => onDimensionChange('maxWidth', (e.target as HTMLInputElement).value)}
				/>
			</div>

			<!-- Height Range -->
			<div class="flex items-center gap-2">
				<label for="min-height" class="text-sm text-muted">Height:</label>
				<input
					id="min-height"
					type="number"
					placeholder="Min"
					class="h-9 w-20 rounded-lg border border-border bg-surface px-3 text-sm text-foreground focus:border-primary focus:outline-none"
					value={filters.minHeight ?? ''}
					oninput={(e) => onDimensionChange('minHeight', (e.target as HTMLInputElement).value)}
				/>
				<span class="text-muted">-</span>
				<input
					id="max-height"
					type="number"
					placeholder="Max"
					aria-label="Maximum height"
					class="h-9 w-20 rounded-lg border border-border bg-surface px-3 text-sm text-foreground focus:border-primary focus:outline-none"
					value={filters.maxHeight ?? ''}
					oninput={(e) => onDimensionChange('maxHeight', (e.target as HTMLInputElement).value)}
				/>
			</div>
		</div>
	{/if}
</div>

<style lang="postcss">
	@reference "tailwindcss";
	.filter-container {
		max-width: 1100px;
		margin: 0 auto;
		padding: 0 1.5rem;
	}
</style>
