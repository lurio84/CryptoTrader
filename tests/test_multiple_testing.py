"""Tests for analysis/multiple_testing.py."""

import pytest

from analysis.multiple_testing import (
    bonferroni_alpha,
    bh_fdr_passes,
    print_multiple_testing_note,
)


def test_bonferroni_alpha_basic():
    assert bonferroni_alpha(10, 0.05) == pytest.approx(0.005)


def test_bonferroni_alpha_alpha_default():
    assert bonferroni_alpha(20) == pytest.approx(0.0025)


def test_bonferroni_alpha_zero_raises():
    with pytest.raises(ValueError):
        bonferroni_alpha(0)


def test_bh_fdr_empty():
    assert bh_fdr_passes([]) == []


def test_bh_fdr_single_below_alpha():
    # n=1: threshold = 1*0.05/1 = 0.05. p=0.02 passes.
    assert bh_fdr_passes([0.02], alpha=0.05) == [True]


def test_bh_fdr_single_above_alpha():
    assert bh_fdr_passes([0.10], alpha=0.05) == [False]


def test_bh_fdr_classic_example():
    """Worked BH example, n=10 alpha=0.05.

    Thresholds k*alpha/n = [0.005, 0.01, 0.015, 0.02, 0.025, 0.03, 0.035, 0.04, 0.045, 0.05].
    Largest k with p_(k) <= threshold is k=7 (0.0298 <= 0.035); p_(8)=0.345 fails.
    """
    p_values = [0.0001, 0.0004, 0.0019, 0.0095, 0.0201, 0.0278, 0.0298, 0.3450, 0.4590, 0.6529]
    result = bh_fdr_passes(p_values, alpha=0.05)
    assert result[:7] == [True] * 7
    assert result[7:] == [False] * 3


def test_bh_fdr_preserves_input_order():
    """Even if input is unsorted, output aligns with input positions."""
    p_values = [0.6529, 0.0001, 0.4590, 0.0004]
    result = bh_fdr_passes(p_values, alpha=0.05)
    # Sorted: [(1, 0.0001), (3, 0.0004), (2, 0.4590), (0, 0.6529)]
    # n=4, k=1: 0.0001 <= 0.0125 -> pass
    # k=2: 0.0004 <= 0.025 -> pass
    # k=3: 0.4590 <= 0.0375 -> fail (stop)
    # threshold_k = 2: positions 1 and 3 (in original order) pass.
    assert result == [False, True, False, True]


def test_bh_fdr_less_conservative_than_bonferroni():
    """BH-FDR should pass at least as many hypotheses as Bonferroni in typical cases."""
    p_values = [0.001, 0.01, 0.03, 0.04, 0.06]
    alpha = 0.05
    bonf = bonferroni_alpha(len(p_values), alpha)  # 0.01
    bonf_passes = [p <= bonf for p in p_values]    # [T, T, F, F, F]
    bh = bh_fdr_passes(p_values, alpha)            # at least 2 pass
    assert sum(bh) >= sum(bonf_passes)


def test_print_multiple_testing_note_smoke(capsys):
    """Smoke test the printer with observed p-values."""
    print_multiple_testing_note(
        n_hypotheses=20,
        observed_p_values={"funding": 0.001, "crash": 0.02, "noise": 0.5},
        alpha=0.05,
    )
    out = capsys.readouterr().out
    assert "Multiple-testing context" in out
    assert "Bonferroni" in out
    assert "funding" in out
    assert "0.0025" in out  # 0.05/20
