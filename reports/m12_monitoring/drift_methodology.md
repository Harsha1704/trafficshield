# TrafficShield Statistical Drift Methodology & Data Quality Engine

**Milestone:** M12 — Intelligent Monitoring, Drift Detection & Model Lifecycle  
**Repository:** `D:\projects\TrafficShield`  
**Date:** 2026-10-23  

---

## 1. Overview and Objectives

Network anomaly detection models operate in dynamic, non-stationary environments. Over time, benign software updates, routing reconfigurations, server migrations, or novel attack vectors induce **covariate shift** (changes in $P(X)$) and **concept shift** (changes in $P(Y \mid X)$).

The TrafficShield drift engine provides rigorous, explainable distribution monitoring across:
1. **Input Forward-Observable Features:** Continuous tracking of the 13 production features.
2. **Continuous Anomaly Scores:** Monitoring shifts in the output score probability density.
3. **Data Quality & Schema Bounds:** Detecting missing values, NaNs, infinities, and physical range boundary violations.

---

## 2. Mathematical Formulations

### 2.1 Population Stability Index (PSI)
The Population Stability Index measures the distance between a reference distribution $Q$ (baseline) and a current empirical distribution $P$ across $B$ bins:

$$\text{PSI} = \sum_{b=1}^{B} \left( P_b - Q_b \right) \times \ln\left( \frac{P_b}{Q_b} \right)$$

#### Quantile Binning & Laplace Smoothing
- **Bin Construction:** Quantile bin cutoffs are determined exclusively from the baseline reference profile using deciles ($B=10$).
- **Smoothing:** To prevent division by zero or undefined logarithms when the current distribution contains empty bins, Laplace smoothing with $\epsilon = 10^{-4}$ is applied:

$$P_b = \frac{N_{b}^{\text{curr}} + \epsilon}{\sum_{j=1}^{B} N_{j}^{\text{curr}} + \epsilon \cdot B}, \quad Q_b = \frac{N_{b}^{\text{base}} + \epsilon}{\sum_{j=1}^{B} N_{j}^{\text{base}} + \epsilon \cdot B}$$

#### Decision Thresholds & Interpretation
| PSI Range | Status | Interpretation | Operational Action |
|:---:|:---:|:---|:---|
| $\text{PSI} < 0.10$ | **STABLE** | Insignificant distribution shift; feature profile aligns with baseline. | Normal inference; no alert. |
| $0.10 \le \text{PSI} < 0.25$ | **WARNING** | Moderate distribution shift; noticeable variance in traffic transport profile. | Log warning alert; SOC analyst review. |
| $\text{PSI} \ge 0.25$ | **CRITICAL** | Severe distribution shift; substantial covariate departure from baseline. | High-priority monitoring alert; feature attribution audit. |

---

### 2.2 Two-Sample Kolmogorov-Smirnov (KS) Test
For continuous features (e.g. `duration_seconds`, `sload`, `sintpkt`), the two-sample KS test evaluates the null hypothesis $H_0$ that the baseline and current distributions are identical:

$$D = \sup_{x} \left| F_{\text{base}}(x) - F_{\text{curr}}(x) \right|$$

- **Statistic $D \in [0, 1]$:** Represents the maximum vertical deviation between empirical cumulative distribution functions (ECDFs).
- **Asymptotic $p$-value:** Calculated via scipy's `ks_2samp`. If $D \ge 0.15$ and $p < 0.01$, a moderate distribution shift is confirmed. If $D \ge 0.25$ and $p < 0.001$, a severe distribution shift is declared.

---

### 2.3 Wasserstein Distance ($\mathcal{W}_1$)
The first Wasserstein distance (Earth Mover's Distance) measures the minimum work required to transform the current distribution into the baseline distribution:

$$\mathcal{W}_1(u, v) = \int_{-\infty}^{\infty} |U(x) - V(x)| \, dx$$

Wasserstein distance provides a scale-dependent physical metric (e.g. measured in hops for `sttl`, or bytes for `fwd_bytes`).

---

## 3. Sample Size Safeguards: Preventing Spurious Micro-Batch Alerts

### The Small Sample Problem
Calculating empirical deciles or KS statistics over tiny samples ($N < 30$) results in massive sampling variance. A benign micro-batch of 8 DNS flows can easily yield a false $\text{PSI} > 0.40$ simply due to quantile sparsity.

### Safeguard Contract
When $N < 30$ (configurable via `DRIFT_MIN_SAMPLE_SIZE`):
- The drift engine **refuses** to emit false drift alarms.
- The feature status is returned as `INSUFFICIENT_DATA`.
- The report includes an explanatory message:
  > *"Sample count (N=10) is below statistical reliability threshold (30). Drift testing deferred until sufficient flows accumulate."*

---

## 4. Reference Baseline Provenance

The reference baseline is immutable, auditable, and stored at `artifacts/monitoring/reference_baseline.json`:
- **Source Dataset:** UNSW-NB15 Day 1 Calibration & Reference Baseline.
- **Source File:** `UNSW-NB15_1.csv` (First 5,000 forward-monitored flows, filtered for non-negative duration).
- **Time Window:** Jan 22, 2015 00:00:00 UTC to 12:00:00 UTC.
- **Model Version:** `OptunaTuned_XGBoost v1.0.0`.
- **Model Artifact Checksum:** `c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495`.
- **Preprocessor Checksum:** `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653`.

---

## 5. Non-Causal Scientific Disclaimer

Every drift report, dashboard panel, and export explicitly includes the following disclaimer:
> **"Statistical distribution drift detects input covariate shift or concept drift relative to reference baseline. It does NOT constitute proof of an adversarial cyberattack or operational link failure."**

A significant shift in `sttl` or `sload` may indicate a BGP routing change, a corporate OS upgrade (Windows TTL 128 vs. Linux TTL 64), or a network topology modification rather than a malicious intrusion.
