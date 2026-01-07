"""Tests for the sprite categorization system."""

import pytest

from pinacotheca.categories import CATEGORIES, categorize, get_category_display


class TestCategorize:
    """Tests for the categorize() function."""

    # Portrait tests
    @pytest.mark.parametrize(
        "name",
        [
            "ROME_LEADER_MALE_01",
            "EGYPT_FEMALE_LEADER_02",
            "GREECE_MALE_03",
            "PERSIA_LEADER_FEMALE_01",
            "CARTHAGE_MALE_05",
            "CREDIT_Artist_Name",
        ],
    )
    def test_portraits(self, name: str) -> None:
        assert categorize(name) == "portraits"

    @pytest.mark.parametrize(
        "name",
        [
            "GENERIC_BABY_01",
            "GENERIC_BOY_ROME",
            "GENERIC_GIRL_02",
            "GENERIC_TEEN_MALE",
            "GENERIC_ADULT_FEMALE",
            "GENERIC_SENIOR_01",
            "HISTORICAL_PERSON_ALEXANDER",
        ],
    )
    def test_portraits_all_types(self, name: str) -> None:
        """All portrait types should be in the single 'portraits' category."""
        assert categorize(name) == "portraits"

    def test_portrait_backgrounds_go_to_backgrounds(self) -> None:
        """Portrait backgrounds should be in 'backgrounds' category."""
        assert categorize("PORTRAIT_BACKGROUND_ROME") == "backgrounds"

    # Unit tests
    @pytest.mark.parametrize(
        "name",
        [
            "UNIT_ARCHER_01",
            "UNIT_HOPLITE_GREEK",
            "UNIT_LEGION_ROME",
            "UNIT_CATAPHRACT_PERSIA",
            "UNIT_WAR_ELEPHANT_INDIA",
            "UNIT_CHARIOT_EGYPT",
            "UNIT_TRIREME_GREEK",
        ],
    )
    def test_units(self, name: str) -> None:
        assert categorize(name) == "units"

    @pytest.mark.parametrize(
        "name",
        [
            "UNIT_ACTION_ATTACK",
            "UNIT_ATTACKED_01",
            "UNIT_CAPTURED",
            "UNIT_COOLDOWN_MOVE",
            "UNIT_DAMAGED",
            "UNIT_DEAD",
            "UNIT_FLANKED",
            "UNIT_ROUT",
            "UNIT_KILLED",
            "UNIT_PUSH",
        ],
    )
    def test_unit_actions(self, name: str) -> None:
        assert categorize(name) == "unit_actions"

    def test_unit_traits(self) -> None:
        assert categorize("UNITTRAIT_VETERAN") == "unit_traits"

    def test_unit_effects(self) -> None:
        assert categorize("EFFECTUNIT_BUFF") == "unit_effects"

    # Game concept tests
    def test_crests(self) -> None:
        assert categorize("CREST_ROME") == "crests"

    def test_improvements(self) -> None:
        assert categorize("IMPROVEMENT_FARM") == "improvements"

    @pytest.mark.parametrize("name", ["RESOURCE_IRON", "GOOD_WINE"])
    def test_resources(self, name: str) -> None:
        assert categorize(name) == "resources"

    def test_yields(self) -> None:
        assert categorize("YIELD_FOOD") == "yields"

    def test_techs(self) -> None:
        assert categorize("TECH_IRONWORKING") == "techs"

    def test_laws(self) -> None:
        assert categorize("LAW_SLAVERY") == "laws"

    def test_religions(self) -> None:
        assert categorize("RELIGION_ZOROASTRIANISM") == "religions"

    def test_traits(self) -> None:
        assert categorize("TRAIT_BRAVE") == "traits"

    def test_specialists(self) -> None:
        assert categorize("SPECIALIST_PRIEST") == "specialists"

    def test_missions(self) -> None:
        assert categorize("MISSION_SPY") == "missions"

    def test_projects(self) -> None:
        assert categorize("PROJECT_WONDER") == "projects"

    def test_terrains(self) -> None:
        assert categorize("TERRAIN_DESERT") == "terrains"

    def test_families(self) -> None:
        assert categorize("FAMILY_JULIUS") == "families"

    def test_nations(self) -> None:
        assert categorize("NATION_ROME") == "nations"

    def test_councils(self) -> None:
        assert categorize("COUNCIL_WAR") == "councils"

    def test_theology(self) -> None:
        assert categorize("THEOLOGY_MONOTHEISM") == "theology"

    @pytest.mark.parametrize(
        "name",
        [
            "GREEK_GOD_ZEUS",
            "ROMAN_GODDESS_MINERVA",
            "EGYPTIAN_GOD_RA",
        ],
    )
    def test_gods(self, name: str) -> None:
        assert categorize(name) == "gods"

    # Game state tests
    def test_bonuses(self) -> None:
        assert categorize("BONUS_PRODUCTION") == "bonuses"

    def test_cooldowns(self) -> None:
        assert categorize("COOLDOWN_ABILITY") == "cooldowns"

    def test_achievements(self) -> None:
        assert categorize("ACHIEVEMENT_CONQUEROR") == "achievements"

    def test_events_images(self) -> None:
        assert categorize("EVENT_PLAGUE") == "events_images"

    @pytest.mark.parametrize("name", ["DIPLOMACY_WAR", "AI_DECLARE_WAR", "BARB_RAID"])
    def test_diplomacy(self, name: str) -> None:
        assert categorize(name) == "diplomacy"

    def test_city(self) -> None:
        assert categorize("CITY_GROWTH") == "city"

    def test_military_goes_to_unit_effects(self) -> None:
        """Military status sprites now go to unit_effects category."""
        assert categorize("MILITARY_STRENGTH") == "unit_effects"

    def test_military_defeat_goes_to_backgrounds(self) -> None:
        """MILITARY_DEFEAT specifically goes to backgrounds."""
        assert categorize("MILITARY_DEFEAT") == "backgrounds"

    def test_status(self) -> None:
        assert categorize("STATUS_WOUNDED") == "status"

    def test_effects(self) -> None:
        assert categorize("EFFECT_BUFF") == "effects"

    # UI tests
    @pytest.mark.parametrize("name", ["UI_BUTTON", "HUD_MINIMAP", "ICON_GOLD", "PING_ALERT"])
    def test_ui_hud_in_events(self, name: str) -> None:
        """HUD elements now go to events_images (displayed as 'UI')."""
        assert categorize(name) == "events_images"

    @pytest.mark.parametrize("name", ["button_primary", "Button_Cancel", "ACTION_MOVE"])
    def test_ui_buttons_in_events(self, name: str) -> None:
        """Button elements now go to events_images (displayed as 'UI')."""
        assert categorize(name) == "events_images"

    @pytest.mark.parametrize(
        "name", ["Frame_Gold", "Panel_Info", "Window_Main", "Border_Fancy", "Background_Dark"]
    )
    def test_ui_frames_in_events(self, name: str) -> None:
        """Frame/panel elements now go to events_images (displayed as 'UI')."""
        assert categorize(name) == "events_images"

    @pytest.mark.parametrize("name", ["Arrow_Up", "Scroll_Bar", "Tab_Active", "Menu_Item"])
    def test_ui_elements_in_events(self, name: str) -> None:
        """UI misc elements now go to events_images (displayed as 'UI')."""
        assert categorize(name) == "events_images"

    # Other categories
    def test_character_select(self) -> None:
        """CHARACTER_SELECT_FRAME ends with Frame, so goes to events_images (UI)."""
        assert categorize("CHARACTER_SELECT_FRAME") == "events_images"

    def test_tools(self) -> None:
        assert categorize("TOOL_HAMMER") == "tools"

    @pytest.mark.parametrize(
        "name",
        [
            "Colosseum_Day",
            "Colossus_Rhodes",
            "Pantheon_Rome",
            "Library_Alexandria",
            "Hanging_Gardens",
        ],
    )
    def test_wonders(self, name: str) -> None:
        assert categorize(name) == "wonders"

    # Catch-all
    def test_other_catchall(self) -> None:
        assert categorize("random_unknown_sprite") == "other"
        assert categorize("xyz123") == "other"

    # Case insensitivity
    def test_case_insensitive(self) -> None:
        assert categorize("crest_rome") == "crests"
        assert categorize("CREST_ROME") == "crests"
        assert categorize("Crest_Rome") == "crests"


class TestCategoryDisplay:
    """Tests for get_category_display()."""

    def test_known_category(self) -> None:
        name, icon = get_category_display("portraits")
        assert name == "Portraits"
        assert icon == "👤"

    def test_unknown_category(self) -> None:
        name, icon = get_category_display("unknown_category")
        assert name == "Unknown Category"
        assert icon == "📁"

    def test_all_categories_have_display(self) -> None:
        """All defined categories should have display info."""
        from pinacotheca.categories import CATEGORY_INFO

        for cat in CATEGORIES:
            assert cat in CATEGORY_INFO, f"Category '{cat}' missing from CATEGORY_INFO"


class TestCategoryOrder:
    """Tests for category pattern ordering."""

    def test_specific_before_general(self) -> None:
        """More specific patterns should match before general ones."""
        # UNIT_ARCHER should match 'units', not 'unit_actions'
        assert categorize("UNIT_ARCHER_01") == "units"
        # UNIT_ACTION should match 'unit_actions'
        assert categorize("UNIT_ACTION_ATTACK") == "unit_actions"

    def test_portraits_before_other(self) -> None:
        """Portrait patterns should match before catch-all."""
        assert categorize("ROME_MALE_01") == "portraits"
        assert categorize("GENERIC_ADULT_01") == "portraits"

    def test_other_is_last(self) -> None:
        """The 'other' category should be the last pattern."""
        categories_list = list(CATEGORIES.keys())
        assert categories_list[-1] == "other"
