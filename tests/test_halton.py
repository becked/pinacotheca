"""Tests for the Halton low-discrepancy sequence port.
CI-safe — no game install required."""

from __future__ import annotations

import pytest

from pinacotheca.halton import halton_sequence, halton_sequence_2d

# ============================================================
# halton_sequence — known values
# ============================================================
#
# Hand-computed reference values, working from the radical-inverse
# definition with the C# pre-increment (index=0 maps to the first
# sequence entry, not zero):
#
#   prime=2: index=0→radical_inverse(1)=0.5
#                     1→radical_inverse(2)=0b10 reversed → 0.01₂ = 0.25
#                     2→radical_inverse(3)=0b11 reversed → 0.11₂ = 0.75
#                     3→radical_inverse(4)=0b100 reversed → 0.001₂ = 0.125
#                     4→radical_inverse(5)=0b101 reversed → 0.101₂ = 0.625
#
#   prime=3: index=0→radical_inverse_3(1)=1/3
#                     1→radical_inverse_3(2)=2/3
#                     2→radical_inverse_3(3)="10"₃ reversed → 0.01₃ = 1/9
#                     3→radical_inverse_3(4)="11"₃ reversed → 0.11₃ = 1/3 + 1/9 = 4/9


@pytest.mark.parametrize(
    "index,expected",
    [
        (0, 0.5),
        (1, 0.25),
        (2, 0.75),
        (3, 0.125),
        (4, 0.625),
    ],
)
def test_halton_sequence_base_2(index: int, expected: float) -> None:
    assert halton_sequence(index, 2) == pytest.approx(expected, abs=1e-12)


@pytest.mark.parametrize(
    "index,expected",
    [
        (0, 1 / 3),
        (1, 2 / 3),
        (2, 1 / 9),
        (3, 4 / 9),
    ],
)
def test_halton_sequence_base_3(index: int, expected: float) -> None:
    assert halton_sequence(index, 3) == pytest.approx(expected, abs=1e-12)


def test_halton_sequence_negative_index_returns_zero() -> None:
    """C# loop precondition is `index > 0` (post-increment); negative input
    yields a non-positive `index + 1`, the loop never runs, returns 0."""
    assert halton_sequence(-1, 2) == 0.0
    assert halton_sequence(-5, 3) == 0.0


def test_halton_sequence_stays_in_unit_interval() -> None:
    for i in range(0, 5000):
        for prime in (2, 3, 5, 7):
            v = halton_sequence(i, prime)
            assert 0.0 <= v < 1.0


# ============================================================
# halton_sequence_2d — pair shape + determinism
# ============================================================


def test_halton_sequence_2d_pairs_base_2_and_3() -> None:
    """The 2D variant must yield (base-2, base-3) — that's the hard-coded
    pairing in `MathUtilities.HaltonSequence2D`."""
    for i in range(0, 100):
        x, y = halton_sequence_2d(i)
        assert x == halton_sequence(i, 2)
        assert y == halton_sequence(i, 3)


def test_halton_sequence_2d_is_deterministic() -> None:
    """Identical inputs → identical outputs across calls (the procedural
    layout depends on this for stable git diffs)."""
    a = [halton_sequence_2d(i) for i in range(50)]
    b = [halton_sequence_2d(i) for i in range(50)]
    assert a == b


def test_halton_sequence_2d_first_values_snapshot() -> None:
    """Lock down the first three pairs to catch any accidental algorithm
    drift."""
    assert halton_sequence_2d(0) == (0.5, 1 / 3)
    assert halton_sequence_2d(1) == (0.25, 2 / 3)
    assert halton_sequence_2d(2) == (0.75, 1 / 9)
