<script lang="ts">
	import type { CategoryData, Sprite } from '$lib/types';

	interface Props {
		category: string;
		categoryData: CategoryData;
		representativeSprite: Sprite | undefined;
		onclick: () => void;
	}

	let { category, categoryData, representativeSprite, onclick }: Props = $props();
</script>

<button
	class="group flex flex-col items-center text-center transition-transform hover:-translate-y-1"
	{onclick}
>
	<div style="margin-bottom: 0.75rem; aspect-ratio: 1; width: 100%; display: flex; align-items: center; justify-content: center; border-radius: 0.5rem; background-color: #3f3833; padding: 1.5rem;">
		{#if representativeSprite}
			<img
				src={representativeSprite.path}
				alt={categoryData.displayName}
				loading="lazy"
				decoding="async"
				style="max-height: 100%; max-width: 100%; object-fit: contain; image-rendering: pixelated;"
			/>
		{:else}
			<span class="text-4xl">{categoryData.icon}</span>
		{/if}
	</div>
	<span class="font-medium text-foreground group-hover:text-primary">
		{categoryData.displayName}
	</span>
	<span class="text-sm text-muted">
		{categoryData.count.toLocaleString()} sprites
	</span>
</button>
