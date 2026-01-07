// Mirrors Python's CATEGORY_INFO from src/pinacotheca/categories.py

export interface CategoryInfo {
	displayName: string;
	icon: string;
}

export const CATEGORY_INFO: Record<string, CategoryInfo> = {
	// Portraits
	portraits: { displayName: 'Portraits', icon: '👤' },
	// Military
	units: { displayName: 'Units', icon: '⚔️' },
	unit_actions: { displayName: 'Unit Actions', icon: '🎬' },
	unit_traits: { displayName: 'Unit Traits', icon: '🏅' },
	unit_effects: { displayName: 'Unit Effects', icon: '💫' },
	// Game concepts
	crests: { displayName: 'Crests & Emblems', icon: '🛡️' },
	gods: { displayName: 'Gods & Goddesses', icon: '✨' },
	religions: { displayName: 'Religions', icon: '🕯️' },
	improvements: { displayName: 'Improvements', icon: '🏛️' },
	resources: { displayName: 'Resources', icon: '💎' },
	yields: { displayName: 'Yields', icon: '📊' },
	techs: { displayName: 'Technologies', icon: '🔬' },
	laws: { displayName: 'Laws', icon: '📜' },
	traits: { displayName: 'Archetypes', icon: '🎭' },
	councils: { displayName: 'Councils', icon: '👥' },
	specialists: { displayName: 'Specialists', icon: '🎓' },
	missions: { displayName: 'Missions', icon: '🎯' },
	projects: { displayName: 'Projects', icon: '🔨' },
	terrains: { displayName: 'Terrains', icon: '🏔️' },
	families: { displayName: 'Families', icon: '👨‍👩‍👧' },
	nations: { displayName: 'Nations', icon: '🏴' },
	theology: { displayName: 'Theologies', icon: '⛪' },
	wonders: { displayName: 'Wonders', icon: '🏛️' },
	// Game state
	bonuses: { displayName: 'Bonuses', icon: '⬆️' },
	cooldowns: { displayName: 'Cooldowns', icon: '⏱️' },
	achievements: { displayName: 'Achievements', icon: '🏆' },
	events_images: { displayName: 'UI', icon: '📰' },
	diplomacy: { displayName: 'Diplomacy', icon: '🤝' },
	city: { displayName: 'City', icon: '🏙️' },
	military: { displayName: 'Military Status', icon: '🎖️' },
	status: { displayName: 'Status Icons', icon: '📍' },
	effects: { displayName: 'Effects', icon: '✨' },
	// UI
	ui_buttons: { displayName: 'Buttons', icon: '🔘' },
	ui_frames: { displayName: 'Frames & Panels', icon: '🪟' },
	ui_hud: { displayName: 'HUD Elements', icon: '🖥️' },
	ui_misc: { displayName: 'UI Misc', icon: '🎨' },
	// Other
	character_select: { displayName: 'Character Select', icon: '👆' },
	tools: { displayName: 'Tools', icon: '🔧' },
	backgrounds: { displayName: 'Backgrounds', icon: '🖼️' },
	other: { displayName: 'Other', icon: '📁' }
};

export function getCategoryInfo(category: string): CategoryInfo {
	return CATEGORY_INFO[category] ?? { displayName: category.replace(/_/g, ' '), icon: '📁' };
}
