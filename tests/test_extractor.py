"""Tests for extractor helpers — `_derive_rig_family` (multi-creature
resource prefab splitting) and `variant_output_names` (co-named sprite
variant naming). Other extractor logic is exercised end-to-end in the
sprite-rendering pipeline."""

from __future__ import annotations

from pinacotheca.extractor import ICON_SUFFIX, _derive_rig_family, variant_output_names


def test_derive_rig_family_handles_basic_rig_names() -> None:
    """Plain `<Family>_Rig` → uppercase family."""
    assert _derive_rig_family("Crab_Rig") == "CRAB"
    assert _derive_rig_family("Goat_Rig") == "GOAT"


def test_derive_rig_family_strips_numeric_suffix() -> None:
    """Unity duplicates rigs as `<Name> (N)` — strip that suffix
    before family derivation."""
    assert _derive_rig_family("Crab_Rig (5)") == "CRAB"
    assert _derive_rig_family("Bird_Seagull_Rig (2)") == "BIRD_SEAGULL"
    assert _derive_rig_family("Goat_Rig (1)") == "GOAT"


def test_derive_rig_family_strips_single_suffix() -> None:
    """The SoloResource-tagged rig usually ends in `_single` — that
    suffix should not bleed into the family name."""
    assert _derive_rig_family("Crab_Rig_single") == "CRAB"
    assert _derive_rig_family("Fish_Sea_Bass_Rig_single") == "FISH_SEA_BASS"


def test_derive_rig_family_handles_compound_names() -> None:
    """Multi-word rig names produce multi-word families (joined with
    underscores). No reduction to a single word."""
    assert _derive_rig_family("Bird_Seagull_Rig") == "BIRD_SEAGULL"
    assert _derive_rig_family("Fish_Sea_Bass_Rig") == "FISH_SEA_BASS"
    assert _derive_rig_family("CowDairy_Rig_2") == "COWDAIRY"


def test_variant_output_names_single_variant_is_bare_name() -> None:
    """The common case — one sprite per name — keeps the bare `{name}.png`
    with no suffix, so nothing changes for the ~4100 non-colliding names."""
    assert variant_output_names("UNIT_ARCHER", 1) == ["UNIT_ARCHER.png"]


def test_variant_output_names_two_variants_primary_plus_icon() -> None:
    """A name with two variants (full art + small UI glyph): the largest
    keeps the bare name, the smaller takes the `__ICON` role suffix."""
    assert variant_output_names("UNIT_ARCHER", 2) == [
        "UNIT_ARCHER.png",
        "UNIT_ARCHER__ICON.png",
    ]


def test_variant_output_names_three_variants_ordinal_fallback() -> None:
    """The lone base-game 3-variant name (`crown`): extras past the first
    icon get a deterministic ordinal so nothing collides."""
    assert variant_output_names("crown", 3) == [
        "crown.png",
        "crown__ICON.png",
        "crown__ICON_2.png",
    ]


def test_variant_output_names_zero_is_empty() -> None:
    """No decodable variants → no output files."""
    assert variant_output_names("FOO", 0) == []


def test_variant_output_names_all_unique() -> None:
    """Every emitted filename is distinct for any variant count, so no
    write silently overwrites another on a case-sensitive path."""
    for count in range(1, 12):
        names = variant_output_names("FOO", count)
        assert len(names) == count
        assert len(set(names)) == count


def test_icon_suffix_uses_double_underscore() -> None:
    """The role separator must be `__` (double): real sprites end in
    `_ICON` (PLAYER_ICON, …) but none contain `__`, so `{name}__ICON`
    can never collide with a genuine sprite name."""
    assert ICON_SUFFIX == "__ICON"
    assert "__" in variant_output_names("PLAYER", 2)[1]
