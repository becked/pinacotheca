"""Tests for extractor helpers — `_derive_rig_family` (multi-creature
resource prefab splitting). Other extractor logic is exercised end-to-end
in the sprite-rendering pipeline."""

from __future__ import annotations

from pinacotheca.extractor import _derive_rig_family


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
