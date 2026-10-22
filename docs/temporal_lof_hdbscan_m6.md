# TrafficShield — Milestone 6: Temporal Features, LOF & HDBSCAN

Version: 1.0  
Date: 2026-10-22  
Milestone: M6

---

## 1. Executive Summary

Milestone 6 expands TrafficShield with:
1. **Causal Temporal and Behavioural Features**: Dynamic rolling indicators (e.g., flow frequency, byte/packet bursts, port diversity, and inter-arrival time) capturing behavioral changes without lookahead leakage.
2. **Local Outlier Factor (LOF)**: Density-based local anomaly detection operating in novelty-detection mode (`novelty=True`).
3. **HDBSCAN Density & Cluster Anomaly Detection**: Unsupervised density-based clustering identifying normal baseline clusters and isolating low-density noise/outliers.

All components adhere strictly to TrafficShield's **unidirectional observability premise**: no reverse-direction traffic assumptions, zero test or attack label usage during model training or threshold selection, and fail-closed artifact serialization.

---

## 2. Causal Temporal Behavioural Feature Engineering

### 2.1 The Need for Behavioural Context
Static per-flow features (such as packet size or duration) may appear normal in isolation, but become anomalous when viewed as part of a high-rate burst, rapid port scan, or irregular inter-arrival pattern.

### 2.2 Strict Causality & Lookahead Prevention
To prevent data leakage and simulate real-time edge monitoring:
- For an observation $i$ arriving at timestamp $t_i$, rolling statistics are calculated strictly over the window:
  $$[t_i - W, t_i)$$
- **Exclusion of Current Observation**: The observation at $t_i$ is **never** counted in its own historical window.
- **Zero Future Information**: No subsequent flow ($t > t_i$) can alter the features of observation $i$.
- **Identifier Separation**: Grouping keys (e.g., `src_ip`) are utilized solely as partition lookup keys during rolling computation and are **never** emitted into the numeric feature matrix passed to anomaly detectors.

### 2.3 Engineered Temporal Indicators
| Feature Name | Description | Formula / Semantics |
|---|---|---|
| `inter_arrival_time` | Elapsed seconds since prior flow from this group | $\Delta t = t_i - t_{i-1}$ (fallback: window size if first seen) |
| `rolling_flow_count` | Number of flows observed in lookback window | Count of events in $[t_i - W, t_i)$ |
| `rolling_packet_sum` | Total packets emitted in lookback window | Sum of forward packets in $[t_i - W, t_i)$ |
| `rolling_byte_sum` | Total bytes emitted in lookback window | Sum of forward bytes in $[t_i - W, t_i)$ |
| `rolling_packet_rate` | Average packet rate over the active window | $\frac{\text{rolling\_packet\_sum}}{\max(1.0, W)}$ |
| `rolling_byte_rate` | Average byte rate over the active window | $\frac{\text{rolling\_byte\_sum}}{\max(1.0, W)}$ |
| `rolling_dst_port_diversity`| Number of distinct destination ports targeted | Cardinality $|\{ \text{dst\_port}_k \} \text{ for } k \in [t_i - W, t_i)|$ |
| `burst_packet_ratio` | Ratio of current packets to past mean packets | $\frac{\text{fwd\_packets}_i}{\text{mean\_past\_packets} + 10^{-6}}$ |
| `log_*` | Log1p-transformed variants for heavy-tailed counts | $\ln(1 + x)$ |

---

## 3. Local Outlier Factor (LOF) Detector

### 3.1 Novelty Detection Mode
Standard LOF in `scikit-learn` computes outlier factors only for the points used during fit (`novelty=False`). In TrafficShield, training traffic must remain isolated from calibration and test traffic.
`LOFDetector` configures `novelty=True`, which fits a $k$-nearest neighbors graph on unlabelled training flows and allows subsequent scoring of unseen calibration and test flows.

### 3.2 Scoring Convention
In `scikit-learn`, `score_samples()` returns negative outlier factors where lower (more negative) values indicate greater abnormality.
TrafficShield enforces a unified standard across all detectors: **HIGHER SCORES STRICTLY INDICATE GREATER ANOMALOUSNESS**.
`LOFDetector` inverts the raw score:
$$\text{anomaly\_score}(x) = - \text{score\_samples}(x)$$
Higher scores now indicate greater local density departure.

### 3.3 Persistence & Checksum Verification
`LOFDetector` integrates with TrafficShield's artifact subsystem (`detection/artifacts.py`), saving the model payload along with its SHA-256 manifest and training feature metadata. Tampered or missing manifests are rejected fail-closed.

---

## 4. HDBSCAN Density & Cluster Anomaly Detection

### 4.1 Concept and Strengths
HDBSCAN (Hierarchical Density-Based Spatial Clustering of Applications with Noise) finds clusters of arbitrary shapes and varying densities while flagging points in sparse regions as noise (label `-1`).
- Identifies multi-modal normal traffic behaviors (e.g. bulk downloads, interactive SSH, periodic DNS).
- Does not assume unimodal or spherical distributions.

### 4.2 In-Sample vs. Out-of-Sample Scoring Semantics
1. **In-Sample Scoring (Training Data)**:
   Scikit-learn's `HDBSCAN` exposes `probabilities_`, which represent the probability that a sample belongs to its assigned cluster (noise samples receive probability $0.0$).
   In-sample outlierness is derived as:
   $$\text{score}_{\text{train}}(x) = 1.0 - \text{probabilities}_x$$
   where $1.0$ is maximum outlier/noise.

2. **Out-of-Sample Scoring (Calibration & Test Data)**:
   Scikit-learn's `HDBSCAN` implementation does not provide a native hierarchical prediction tree for unseen out-of-sample points.
   To evaluate unseen calibration and test observations without refitting the model, `HDBSCANDetector`:
   - Extracts the cluster medoids during training.
   - For an unseen point $x$, computes the Euclidean distance to the nearest normal cluster medoid:
     $$d_{\min}(x) = \min_{c} \|x - \text{medoid}_c\|_2$$
   - Standardizes the distance by the robust training scale $\sigma_{\text{MAD}}$:
     $$\text{score}(x) = \frac{d_{\min}(x)}{\sigma_{\text{MAD}}}$$
   Higher values strictly indicate greater distance from any learned normal traffic cluster.

---

## 5. CLI & Evaluation Protocol Integration

All detectors are unified under the evaluation framework (`evaluation/cli.py` & `scripts/evaluate_dataset.py`):

```bash
# Evaluate LOF with causal temporal features on unlabelled data
python -m evaluation.cli \
    --data datasets/interim/ugr16/ugr16_201603.csv \
    --detector lof \
    --use-temporal-features \
    --temporal-window 300.0 \
    --lof-neighbors 20 \
    --quantile 0.99 \
    --out-dir reports/evaluation

# Evaluate HDBSCAN detector
python -m evaluation.cli \
    --data datasets/interim/ugr16/ugr16_201603.csv \
    --detector hdbscan \
    --hdbscan-min-cluster-size 10 \
    --quantile 0.99 \
    --out-dir reports/evaluation
```

### Evaluation Protocol Guarantees
- **No Label Leakage**: Thresholds are established solely on the calibration split via quantile cutoff before ground-truth labels are joined.
- **Reporting**: Full binary metrics, continuous ranking metrics (ROC-AUC, PR-AUC), category breakdowns, and confusion matrices are emitted to machine-readable JSON and CSV.
