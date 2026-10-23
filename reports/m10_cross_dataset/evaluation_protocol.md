# TrafficShield Milestone 10: Evaluation Protocol & Methodology
**Date:** 2026-10-23  

---

## 1. Multi-Track Evaluation Design

TrafficShield M10 implements three rigorous evaluation tracks:

### Track A — Dataset-Specific Baseline (CICIDS2017)
- **Objective:** Train and evaluate a native model on CICIDS2017 using its own validated forward-observable features.
- **Protocol:** Time-ordered or session-based splitting with zero leakage.
- **Local Reality:** CICIDS2017 raw files are not downloaded. In accordance with project integrity rules, Track A on real data is documented as **`NOT RUN (Dataset absent locally)`**. The adapter and validation framework are verified on a synthetic fixture.

### Track B — Cross-Dataset Transfer
- **Direct Production Model Transfer:** Evaluated against feature contract. Marked **`DIRECT TRANSFER UNSUPPORTED`** due to missing `sttl` and `is_sm_ips_ports`.
- **Common-Subspace Model Transfer:** Evaluates a model trained exclusively on the 9 common forward-observable features. Trained on UNSW-NB15 Day 1, tested on held-out UNSW-NB15 Test (within-dataset baseline) vs zero-shot transfer onto CICIDS2017.

### Track C — Multi-Capture & Temporal Robustness (UNSW-NB15 Day 1 vs Day 2)
- **Objective:** Test model generalization across a **24-day time gap** between independent recording days (Jan 22, 2015 vs Feb 15, 2015).
- **Metrics:** Kolmogorov-Smirnov 2-sample test, Wasserstein distance, False Positive Rate shift, and Attack Recall degradation.

---

## 2. Metric Verification Standard

All metrics satisfy exact arithmetic consistency:
$$\\text{Balanced Accuracy} = \\frac{\\text{Recall} + \\text{Specificity}}{2}$$
$$\\text{F1 Score} = \\frac{2 \\cdot \\text{Precision} \\cdot \\text{Recall}}{\\text{Precision} + \\text{Recall}}$$
