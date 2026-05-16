"""Multiple-comparisons helpers for research scripts.

The repo evaluates ~20+ candidate signals (Fear&Greed, MVRV, NVT, RSI, halving,
DXY, stablecoin dominance, funding, crash variants...) before settling on the
3 that survive. The pre-existing safeguard is IS/OOS temporal split + Mann-Whitney
on IS + positive OOS delta; this module adds Bonferroni and Benjamini-Hochberg
FDR as informational context so the reader can see how a raw p-value reads
once multiple-testing is taken into account.

NOT a decision gate -- the production gate is still IS+OOS+positive. The note
exists to make the rigor explicit.
"""

from __future__ import annotations


def bonferroni_alpha(n_hypotheses: int, alpha: float = 0.05) -> float:
    """Bonferroni-corrected alpha: alpha / n. Conservative, controls FWER."""
    if n_hypotheses <= 0:
        raise ValueError("n_hypotheses must be >= 1")
    return alpha / n_hypotheses


def bh_fdr_passes(p_values: list[float], alpha: float = 0.05) -> list[bool]:
    """Vectorized Benjamini-Hochberg FDR procedure.

    Returns a list aligned with `p_values`: True if the hypothesis would pass
    the BH-FDR at level `alpha`, False otherwise. Less conservative than
    Bonferroni when several hypotheses have small p-values.

    Procedure: sort p-values ascending; find the largest k such that
    p_(k) <= k * alpha / n; reject all hypotheses ranked 1..k.
    """
    n = len(p_values)
    if n == 0:
        return []
    ranked = sorted(enumerate(p_values), key=lambda x: x[1])
    threshold_k = 0
    for k, (_, p) in enumerate(ranked, start=1):
        if p <= k * alpha / n:
            threshold_k = k
    result = [False] * n
    for k in range(threshold_k):
        idx = ranked[k][0]
        result[idx] = True
    return result


def print_multiple_testing_note(
    n_hypotheses: int,
    observed_p_values: dict[str, float] | None = None,
    alpha: float = 0.05,
) -> None:
    """Print an informational block contextualising raw p-values against
    multiple-testing corrections. Intended at the end of a research script.

    If `observed_p_values` is given (name -> p), also reports which would
    pass Bonferroni and BH-FDR. The repo's actual production gate is
    IS p<0.05 + positive OOS delta; this is purely informational.
    """
    bonf = bonferroni_alpha(n_hypotheses, alpha)
    print()
    print("--- Multiple-testing context (informational) ---")
    print("  Total hypotheses considered: {}".format(n_hypotheses))
    print("  Family-wise alpha (Bonferroni): p <= {:.5f}".format(bonf))

    if not observed_p_values:
        print("  Provide observed_p_values=dict to see per-hypothesis verdicts.")
        print("------------------------------------------------\n")
        return

    names = list(observed_p_values.keys())
    pvals = [observed_p_values[n] for n in names]
    bh = bh_fdr_passes(pvals, alpha)

    print("  Per-hypothesis verdicts (info, NOT the production gate):")
    print("    {:<32} {:>10}  {:>4}  {:>5}".format("hypothesis", "raw p", "Bonf", "BH-FDR"))
    print("    " + "-" * 56)
    for name, p, passes_bh in zip(names, pvals, bh):
        bonf_mark = "OK" if p <= bonf else "X"
        bh_mark = "OK" if passes_bh else "X"
        print("    {:<32} {:>10.4f}  {:>4}  {:>5}".format(name, p, bonf_mark, bh_mark))
    print("------------------------------------------------\n")
