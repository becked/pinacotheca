"""
Sprite categorization system.

Categories are defined as regex patterns matched against sprite names.
Order matters - first match wins, so more specific patterns come before general ones.
"""

import re
from typing import Final

# Category display information: (display_name, emoji_icon)
CATEGORY_INFO: Final[dict[str, tuple[str, str]]] = {
    # Portraits
    "portraits": ("Portraits", "👤"),
    # Military
    "units": ("Military Units", "⚔️"),
    "unit_actions": ("Unit Actions", "🎬"),
    "unit_traits": ("Unit Traits", "🏅"),
    "unit_effects": ("Unit Effects", "💫"),
    # Game concepts
    "crests": ("Crests & Emblems", "🛡️"),
    "gods": ("Gods & Goddesses", "✨"),
    "religions": ("Religions", "🕯️"),
    "improvements": ("Improvements", "🏛️"),
    "resources": ("Resources", "💎"),
    "yields": ("Yields", "📊"),
    "techs": ("Technologies", "🔬"),
    "laws": ("Laws", "📜"),
    "traits": ("Archetypes", "🎭"),
    "councils": ("Councils", "👥"),
    "specialists": ("Specialists", "🎓"),
    "missions": ("Missions", "🎯"),
    "projects": ("Projects", "🔨"),
    "terrains": ("Terrains", "🏔️"),
    "families": ("Families", "👨‍👩‍👧"),
    "nations": ("Nations", "🏴"),
    "theology": ("Theologies", "⛪"),
    "wonders": ("Wonders", "🏛️"),
    # Game state
    "bonuses": ("Bonuses", "⬆️"),
    "cooldowns": ("Cooldowns", "⏱️"),
    "achievements": ("Achievements", "🏆"),
    "events_images": ("UI", "📰"),
    "diplomacy": ("Diplomacy", "🤝"),
    "city": ("City", "🏙️"),
    "military": ("Military Status", "🎖️"),
    "status": ("Status Icons", "📍"),
    "effects": ("Effects", "✨"),
    # UI
    "ui_buttons": ("Buttons", "🔘"),
    "ui_frames": ("Frames & Panels", "🪟"),
    # Other
    "character_select": ("Character Select", "👆"),
    "tools": ("Tools", "🔧"),
    "backgrounds": ("Backgrounds", "🖼️"),
    "other": ("Other", "📁"),
}

# Regex patterns for categorization - ORDER MATTERS (first match wins)
CATEGORIES: Final[dict[str, str]] = {
    # All portraits (nation, generic, historical, backgrounds)
    "portraits": (
        r"^(AKSUM|ASSYRIA|BABYLONIA|CARTHAGE|CHINA|DANE|EGYPT|GAUL|GREECE|HITTITE|"
        r"HUN|HYKSOS|INDIA|KUSH|MAURYA|MITANNI|NUMIDIAN|PERSIA|ROME|SCYTHIAN|"
        r"THRACIAN|VANDAL|YUEZHI|TAMIL)_(LEADER_)?(FEMALE|MALE)_"
        r"|^CREDIT_"
        r"|^GENERIC_(BABY|BOY|GIRL|TEEN|ADULT|SENIOR)"
        r"|^HISTORICAL_PERSON"
        r"|^PORTRAIT_BACKGROUND"
    ),
    # Military units (actual unit types, not actions/effects)
    "units": (
        r"^UNIT_(AFRICAN_ELEPHANT|AKKADIAN|AMAZON|AMUN|ARCHER|ARMOURED|ASSAULT|"
        r"ATENISM|AXEMAN|BALLISTA|BATTERING|BIREME|BUDDHIS|CAMEL|CARAVAN|CATAPHRACT|"
        r"CHARIOT|CHRISTIAN|CIMMERIAN|CLUBTHROWER|CONSCRIPT|CROSSBOW|DMT|DROMON|"
        r"ELITE|FEMALE|GAESATA|GALLEY|HASTATUS|HEAVY|HINDU|HOPLITE|HORSE|HOWDAH|"
        r"HUSCARL|JAVEL|JUDAISM|KUSHAN|KUSHITE|LEGION|LEVY|LIBYAN|LIGHT|LONGBOW|"
        r"MACEMAN|MAHOUT|MANGONEL|MANICHAE|MARAUDER|MEROITIC|MILITIA|NAPATAN|NOMAD|"
        r"ONAGER|PALTON|PELTAST|PHALANG|PIKE|POLYBOLOS|SCOUT|SETTLER|SHOTELAI|SIEGE|"
        r"SKIRMISH|SLINGER|SPEAR|STEPPE|SWORD|THREE|TRIREME|TURRETED|WARLORD|"
        r"WARRIOR|WAR_ELEPHANT|WORKER|ZOROAST)"
    ),
    "unit_actions": (
        r"^UNIT_(ACTION_|ATTACKED|CAPTURED|COOLDOWN|DAMAGED|DEAD|FLANKED|ROUT|KILLED|PUSH)"
    ),
    "unit_traits": r"^UNITTRAIT_",
    "unit_effects": r"^EFFECTUNIT_",
    # Game concepts
    "crests": r"^CREST_",
    "improvements": r"^IMPROVEMENT_",
    "resources": r"^(RESOURCE_|GOOD_)",
    "yields": r"^YIELD_",
    "techs": r"^TECH_",
    "laws": r"^LAW_",
    "religions": r"^RELIGION_",
    "traits": r"^TRAIT_",
    "specialists": r"^SPECIALIST_",
    "missions": r"^(MISSION_|FAMILY_MARRIAGE)",
    "projects": r"^PROJECT_",
    "terrains": r"^TERRAIN_",
    "families": r"^FAMILY_",
    "nations": r"^NATION_",
    "councils": r"^COUNCIL_",
    "theology": r"^THEOLOGY_",
    "gods": r"^[A-Z]+_(GOD|GODDESS)_",
    # Game state/status
    "bonuses": r"^BONUS_",
    "cooldowns": r"^COOLDOWN_",
    "achievements": r"^ACHIEVEMENT",
    "events_images": r"^(EVENT_|Arrow|Scroll|Tab|Menu|Popup|Tooltip|Card|Gradient|Mask|Circle|Square|Bar_|BarIcon|UI_|HUD_|ICON_|PING_|TURN_SUMMARY)|^.*Frame$",
    "diplomacy": r"^(DIPLOMACY_|AI_DECLARE|BARB_)",
    "city": r"^CITY_",
    "military": r"^MILITARY_",
    "status": r"^STATUS_",
    "effects": r"^EFFECT_",
    # UI elements
    "ui_buttons": r"^(button|Button|BUTTON|ACTION)",
    "ui_frames": r"^(Frame|frame|Panel|panel|Window|window|Trim|trim|Border|border|Background|BG|Blur)",
    # Characters
    "character_select": r"^CHARACTER_SELECT",
    # Tools and misc game icons
    "tools": r"^TOOL_",
    "wonders": (
        r"^(Colosseum|Colossus|Pantheon|Library|Acropolis|Heliopolis|Mausoleum|"
        r"Necropolis|Cothon|Circus|Hanging|Bazaar|Oracle)"
    ),
    # Backgrounds (categorized by size in extractor, not regex)
    "backgrounds": r"^$",  # Never matches - size-based categorization in extractor
    # Catch-all (should be minimal now)
    "other": r".*",
}

# Pre-compile patterns for performance
_COMPILED_PATTERNS: dict[str, re.Pattern[str]] = {
    cat: re.compile(pattern, re.IGNORECASE) for cat, pattern in CATEGORIES.items()
}


def categorize(name: str) -> str:
    """
    Categorize a sprite by its name using regex patterns.

    Args:
        name: The sprite name to categorize

    Returns:
        The category key (e.g., 'portraits', 'units', 'other')
    """
    for cat, pattern in _COMPILED_PATTERNS.items():
        if pattern.match(name):
            return cat
    return "other"


def get_category_display(category: str) -> tuple[str, str]:
    """
    Get the display name and icon for a category.

    Args:
        category: The category key

    Returns:
        Tuple of (display_name, emoji_icon)
    """
    return CATEGORY_INFO.get(category, (category.replace("_", " ").title(), "📁"))
