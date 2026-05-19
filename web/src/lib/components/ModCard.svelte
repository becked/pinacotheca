<script lang="ts">
	import type { ModEntry, Sprite } from '$lib/types';

	interface Props {
		mod: ModEntry;
		representativeSprite: Sprite | undefined;
		onclick: () => void;
	}

	let { mod, representativeSprite, onclick }: Props = $props();
</script>

<button
	class="group flex flex-col items-center text-center transition-transform hover:-translate-y-1"
	{onclick}
>
	<div style="margin-bottom: 0.75rem; aspect-ratio: 1; width: 100%; display: flex; align-items: center; justify-content: center; border-radius: 0.5rem; background-color: var(--color-surface-elevated); padding: 1.5rem;">
		{#if representativeSprite}
			<img
				src={representativeSprite.path}
				alt={mod.displayName}
				loading="lazy"
				decoding="async"
				style="max-height: 100%; max-width: 100%; object-fit: contain; image-rendering: pixelated;"
			/>
		{:else}
			<span class="text-4xl">🧩</span>
		{/if}
	</div>
	<span class="font-medium text-foreground group-hover:text-primary">
		{mod.displayName}
	</span>
	{#if mod.author}
		<span class="text-xs text-muted/80" style="font-style: italic;">
			by {mod.author}
		</span>
	{/if}
	<span class="text-sm text-muted">
		{mod.count.toLocaleString()} sprites
	</span>
</button>
