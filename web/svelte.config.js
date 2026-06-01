import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),

	kit: {
		adapter: adapter({
			pages: '../extracted',
			assets: '../extracted',
			fallback: undefined,
			precompress: false,
			strict: true
		}),
		prerender: {
			handleHttpError: ({ path, message }) => {
				// Sprite images are PNG in the local tree; the production bundle
				// references the .webp variants that only exist after
				// pinacotheca-deploy converts them. The prerender crawl can't find
				// them in ../extracted/ — that's expected, don't fail the build.
				if (path.includes('/sprites/')) return;
				throw new Error(message);
			}
		},
		paths: {
			base: process.env.NODE_ENV === 'production' ? '/pinacotheca' : ''
		},
		alias: {
			$components: 'src/lib/components',
			$stores: 'src/lib/stores',
			$utils: 'src/lib/utils'
		}
	}
};

export default config;
