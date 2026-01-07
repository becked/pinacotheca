<script lang="ts">
	import type { Sprite } from '$lib/types';
	import { getCategoryInfo } from '$lib/utils/categories';

	interface Props {
		sprite: Sprite;
		onclick: () => void;
	}

	let { sprite, onclick }: Props = $props();

	let displayName = $derived(() => {
		const name = sprite.name;
		const parts = name.split('_');
		if (parts.length <= 3) return name;
		const lastParts = parts.slice(-3).join('_');
		return lastParts.length < name.length ? lastParts : name;
	});

	let categoryInfo = $derived(getCategoryInfo(sprite.category));

	let fileSize = $derived(() => {
		if (!sprite.size) return '';
		const kb = sprite.size / 1024;
		return kb < 10 ? `${kb.toFixed(1)} KB` : `${Math.round(kb)} KB`;
	});
</script>

<button
	class="group flex flex-col items-center text-center transition-transform hover:-translate-y-1"
	{onclick}
>
	<div style="margin-bottom: 0.75rem; aspect-ratio: 1; width: 100%; display: flex; align-items: center; justify-content: center; border-radius: 0.5rem; background-color: #3f3833; padding: 1.5rem;">
		<img
			src={sprite.path}
			alt={sprite.name}
			loading="lazy"
			decoding="async"
			style="max-height: 100%; max-width: 100%; object-fit: contain; image-rendering: pixelated;"
		/>
	</div>
	<span class="font-medium text-foreground group-hover:text-primary" title={sprite.name}>
		{displayName()}
	</span>
	<span class="text-sm text-muted">
		{sprite.width} x {sprite.height}
	</span>
</button>
