"""
Memory Stability Acceptance Policy for Soak Qualification
==========================================================
Milestone 17.1 — Accounting Invariant Audit & Memory Criteria

Defines explicit, configurable pass/fail criteria for memory stability during
prolonged soak runs, addressing edge cases such as low baseline memory, large
relative growth, large absolute growth, and unavailable hardware readings.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class MemoryStabilityPolicy:
    """
    Configurable criteria for evaluating process memory stability over time.

    Engineering Rationale:
    ----------------------
    1. Operational Context (Warmup vs Steady-State):
       A Python ML pipeline allocates significant memory (~100-150 MB) during initial
       library importation (Scapy, XGBoost, Scikit-Learn) and model unpickling.
       A measurement taken before this initialization reflects cold interpreter state,
       not operational baseline. Steady-state soak evaluation must either sample
       post-warmup baseline or permit library initialization headroom.

    2. Hard Absolute Limit (`max_absolute_growth_mb`, default: 250.0 MB):
       Enforces a strict upper bound on Resident Set Size (RSS) expansion. Even if baseline
       memory is large (e.g., 600 MB after loading models and cache), any expansion greater
       than 250 MB indicates unbounded retention, uncollected cyclic references, or queue leakage.

    3. Proportional Relative Limit (`max_relative_growth_pct`, default: 50.0%):
       Enforces proportional scaling boundaries for typical steady-state operations.

    4. Rule Modes:
       - "OR" (Default, matching M17 specification `< 250 MB or < 50%`):
         Passes if delta RSS is within the absolute bound OR within the relative bound.
         This accommodates cold-start initialization where relative growth is high but
         absolute growth is well within bounded limits.
       - "AND":
         Requires satisfying BOTH the absolute limit AND (relative limit OR minimum headroom).
       - "ABSOLUTE_ONLY":
         Only enforces max_absolute_growth_mb.
       - "RELATIVE_ONLY":
         Only enforces max_relative_growth_pct.

    5. Provisional Status:
       Labeled as proposed acceptance criteria requiring operator review before hard
       production gate lock.
    """

    max_absolute_growth_mb: float = 250.0
    max_relative_growth_pct: float = 50.0
    min_absolute_headroom_mb: float = 50.0
    rule_mode: str = "OR"  # "OR", "AND", "ABSOLUTE_ONLY", "RELATIVE_ONLY"
    is_provisional: bool = True  # Labeled as proposed acceptance criteria requiring operator review

    def evaluate(
        self,
        baseline_rss_mb: float | None,
        final_rss_mb: float | None,
        peak_rss_mb: float | None = None,
    ) -> tuple[bool, str, dict[str, Any]]:
        """
        Evaluate memory stability between baseline and final snapshots.

        Returns:
            (passed, rationale_message, diagnostic_dict)
        """
        diagnostics: dict[str, Any] = {
            "policy": {
                "max_absolute_growth_mb": self.max_absolute_growth_mb,
                "max_relative_growth_pct": self.max_relative_growth_pct,
                "min_absolute_headroom_mb": self.min_absolute_headroom_mb,
                "rule_mode": self.rule_mode,
                "is_provisional": self.is_provisional,
            },
            "baseline_rss_mb": baseline_rss_mb,
            "final_rss_mb": final_rss_mb,
            "peak_rss_mb": peak_rss_mb,
            "delta_rss_mb": None,
            "relative_growth_pct": None,
        }

        # 1. Check measurement availability
        if baseline_rss_mb is None or final_rss_mb is None:
            msg = "Memory stability evaluation FAILED: Missing or unavailable RSS measurements."
            return False, msg, diagnostics

        # 2. Compute deltas
        delta_mb = final_rss_mb - baseline_rss_mb
        effective_delta_mb = max(0.0, delta_mb)
        diagnostics["delta_rss_mb"] = round(delta_mb, 2)

        if baseline_rss_mb > 0.0:
            rel_pct = (effective_delta_mb / baseline_rss_mb) * 100.0
            diagnostics["relative_growth_pct"] = round(rel_pct, 1)
        else:
            rel_pct = 0.0
            diagnostics["relative_growth_pct"] = 0.0

        # 3. Check memory reclamation or negative drift (OS page trimming)
        if delta_mb <= 0.0:
            msg = (
                f"Memory stable: RSS decreased or remained flat "
                f"({baseline_rss_mb:.2f} MB -> {final_rss_mb:.2f} MB, delta {delta_mb:.2f} MB)."
            )
            return True, msg, diagnostics

        # 4. Evaluate based on configured rule_mode
        abs_ok = effective_delta_mb <= self.max_absolute_growth_mb
        rel_ok = (effective_delta_mb <= self.min_absolute_headroom_mb) or (rel_pct <= self.max_relative_growth_pct)

        if self.rule_mode == "ABSOLUTE_ONLY":
            passed = abs_ok
            rule_desc = f"Absolute limit only (delta {effective_delta_mb:.2f} MB <= {self.max_absolute_growth_mb:.2f} MB)"
        elif self.rule_mode == "RELATIVE_ONLY":
            passed = rel_ok
            rule_desc = f"Relative limit only ({rel_pct:.1f}% <= {self.max_relative_growth_pct:.1f}%)"
        elif self.rule_mode == "AND":
            passed = abs_ok and rel_ok
            rule_desc = (
                f"Combined AND (delta {effective_delta_mb:.2f} MB <= {self.max_absolute_growth_mb:.2f} MB "
                f"AND {rel_pct:.1f}% <= {self.max_relative_growth_pct:.1f}%)"
            )
        else:  # Default "OR"
            passed = abs_ok or rel_ok
            rule_desc = (
                f"Combined OR (delta {effective_delta_mb:.2f} MB <= {self.max_absolute_growth_mb:.2f} MB "
                f"OR {rel_pct:.1f}% <= {self.max_relative_growth_pct:.1f}%)"
            )

        if passed:
            msg = (
                f"Memory stable under rule '{self.rule_mode}': "
                f"{rule_desc} satisfied ({baseline_rss_mb:.2f} MB -> {final_rss_mb:.2f} MB)."
            )
        else:
            msg = (
                f"Memory stability FAILED under rule '{self.rule_mode}': "
                f"{rule_desc} breached ({baseline_rss_mb:.2f} MB -> {final_rss_mb:.2f} MB, "
                f"delta {effective_delta_mb:.2f} MB, {rel_pct:.1f}%)."
            )

        return passed, msg, diagnostics
