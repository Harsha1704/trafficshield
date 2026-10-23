# TrafficShield Milestone 9: Out-of-Distribution Temporal Generalization
**Date:** 2026-10-23  
**Dataset:** `UNSW-NB15_3.csv` (Cross-File Day 2 Holdout, 20,000 flows)  
**Trained On:** `UNSW-NB15_1.csv` Day 1 Train split only

---

## 1. Generalization Objective

A critical weakness of published ML intrusion detection models is catastrophic degradation when tested on subsequent recording days. In this evaluation, the production model (trained exclusively on Day 1 flows) was evaluated on **20,000 completely independent flows from Day 2**.

---

## 2. Day 2 Generalization Performance

| Evaluation Metric | Day 1 Held-Out Test (19,942 flows) | Day 2 Temporal Holdout (20,000 flows) | Delta / Degradation |
|:---|:---:|:---:|:---:|
| **Accuracy** | 98.10% | **96.97%** | -1.13% |
| **Attack Precision** | 95.85% | **90.57%** | -5.28% |
| **Attack Recall** | 97.78% | **98.37%** | -0.59% |
| **Specificity** | 98.24% | **96.50%** | -1.74% |
| **False Positive Rate** | 1.76% | **3.50%** | +1.74% |
| **F1 Score** | 0.9681 | **0.9431** | -0.0250 |
| **True Negatives (TN)** | 13,836 | **14,384** | - |
| **False Positives (FP)** | 248 | **522** | - |
| **False Negatives (FN)** | 130 | **83** | - |
| **True Positives (TP)** | 5,728 | **5,011** | - |

---

## 3. Day 2 Per-Category Recall Breakdown

| Attack Category | Day 2 Flow Count | Detected (TP) | Missed (FN) | Recall Rate |
|:---|:---:|:---:|:---:|:---:|
| **Analysis** | 1 | 1 | 0 | **100.00%** |
| **Backdoor** | 5 | 4 | 1 | **80.00%** |
| **Dos** | 53 | 53 | 0 | **100.00%** |
| **Exploits** | 279 | 264 | 15 | **94.62%** |
| **Fuzzers** | 191 | 140 | 51 | **73.30%** |
| **Generic** | 4,422 | 4,420 | 2 | **99.95%** |
| **Reconnaissance** | 123 | 110 | 13 | **89.43%** |
| **Shellcode** | 19 | 18 | 1 | **94.74%** |
| **Worms** | 1 | 1 | 0 | **100.00%** |

---

## 4. Assessment

The model exhibits **exceptional temporal resilience**:
- Held-out Day 2 Accuracy remains at **96.97%**.
- Held-out Day 2 Attack Recall remains at **98.37%** (5,011 of 5,094 attacks detected).
- Zero retraining or domain adaptation was performed.
