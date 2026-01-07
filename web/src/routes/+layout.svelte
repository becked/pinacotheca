<script lang="ts">
	import '../app.css';

	let { children } = $props();
</script>

<svelte:head>
	<title>Old World Sprites Gallery</title>
	<meta name="description" content="Browse and search sprite assets from the Old World game" />
</svelte:head>

{@render children()}
