/**
 * Converts raw sprite names to human-readable display names.
 * Examples:
 *   TRAIT_BUILDER → "Trait: Builder"
 *   UNIT_ACTION_FORTIFY → "Unit Action: Fortify"
 *   ASSYRIA_GOD_ASHUR → "Assyria God: Ashur"
 *   ActionButton → "Action Button"
 */

// Nations and tribes that can appear as prefixes
const NATIONS = new Set([
	'AKSUM',
	'ASSYRIA',
	'BABYLON',
	'BABYLONIA',
	'CARTHAGE',
	'CHINA',
	'EGYPT',
	'GREECE',
	'HITTITE',
	'KUSH',
	'MAURYA',
	'PERSIA',
	'ROME',
	'TAMIL',
	'YUEZHI',
	// Tribes
	'DANE',
	'GAUL',
	'HUN',
	'NUMIDIAN',
	'SCYTHIAN',
	'THRACIAN',
	'VANDAL'
]);

// Compound prefixes (checked first, order matters - longer matches first)
const COMPOUND_PREFIXES: Array<{ match: string[]; label: string }> = [
	{ match: ['UNIT', 'ACTION'], label: 'Unit Action' },
	{ match: ['CREST', 'NATION'], label: 'Nation Crest' },
	{ match: ['CREST', 'ARCHETYPE'], label: 'Archetype Crest' },
	{ match: ['CREST', 'FAMILY'], label: 'Family Crest' },
	{ match: ['CREST', 'TRIBE'], label: 'Tribe Crest' }
];

// Simple prefixes that get a colon format
const SIMPLE_PREFIXES = new Set([
	'ACHIEVEMENT',
	'BONUS',
	'BOOST',
	'CITY',
	'CITYSORT',
	'COOLDOWN',
	'DIPLOMACY',
	'EFFECTUNIT',
	'IMPROVEMENT',
	'JOB',
	'LAW',
	'LAWS',
	'MISSION',
	'PROJECT',
	'PROMOTION',
	'RELIGION',
	'RESOURCE',
	'SPECIALIST',
	'STATUS',
	'TECH',
	'TECHS',
	'TERRAIN',
	'TRAIT',
	'UNIT',
	'UNITTRAIT',
	'VICTORY',
	'WONDER',
	'YIELD'
]);

/**
 * Convert a string to title case (capitalize first letter of each word)
 */
function titleCase(str: string): string {
	return str
		.toLowerCase()
		.split(' ')
		.map((word) => word.charAt(0).toUpperCase() + word.slice(1))
		.join(' ');
}

/**
 * Split a compound word like EFFECTUNIT or UNITTRAIT into separate words
 */
function splitCompoundWord(word: string): string {
	const compounds: Record<string, string> = {
		EFFECTUNIT: 'Effect Unit',
		UNITTRAIT: 'Unit Trait',
		CITYSORT: 'City Sort'
	};
	return compounds[word] || titleCase(word);
}

/**
 * Convert a raw sprite name to a human-readable display name
 */
export function humanizeName(name: string): string {
	// Handle CamelCase names (contain lowercase letters, may have hyphens)
	if (/[a-z]/.test(name)) {
		return name
			.replace(/([a-z])([A-Z])/g, '$1 $2') // Split camelCase
			.replace(/[-_]/g, ' ') // Replace separators with spaces
			.replace(/\s+/g, ' ') // Normalize multiple spaces
			.trim();
	}

	// Handle UPPERCASE_UNDERSCORE names
	const parts = name.split('_');

	// Check for compound prefixes first (e.g., UNIT_ACTION_FORTIFY)
	for (const { match, label } of COMPOUND_PREFIXES) {
		if (parts.length > match.length && match.every((m, i) => parts[i] === m)) {
			const rest = parts.slice(match.length);
			return `${label}: ${titleCase(rest.join(' '))}`;
		}
	}

	// Check for nation + type patterns (e.g., ASSYRIA_GOD_ASHUR)
	if (NATIONS.has(parts[0]) && parts.length > 2) {
		const nation = titleCase(parts[0]);
		const type = titleCase(parts[1]);
		const rest = parts.slice(2);
		return `${nation} ${type}: ${titleCase(rest.join(' '))}`;
	}

	// Check for simple prefixes (e.g., TRAIT_BUILDER)
	if (SIMPLE_PREFIXES.has(parts[0]) && parts.length > 1) {
		const prefix = splitCompoundWord(parts[0]);
		const rest = parts.slice(1);
		return `${prefix}: ${titleCase(rest.join(' '))}`;
	}

	// Fallback: just title case with spaces
	return titleCase(name.replace(/_/g, ' '));
}
