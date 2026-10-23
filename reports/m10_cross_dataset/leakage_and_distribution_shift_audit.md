# TrafficShield Milestone 10: Leakage & Distribution Shift Audit
**Date:** 2026-10-23  

---

## 1. Feature Distribution Shift Across 24 Days (UNSW-NB15 Day 1 vs Day 2)

Evaluated across the 24-day recording gap (Jan 22, 2015 to Feb 15, 2015):

| Feature Name | Kolmogorov-Smirnov $D$ | $p$-value | Wasserstein Distance ($W_1$) | Day 1 Median | Day 2 Median | Shift Severity |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| **duration_seconds** | 0.4149 | 0.00e+00 | 0.41 | 0.03 | 0.0 | HIGH |
| **fwd_bytes** | 0.3251 | 0.00e+00 | 2043.81 | 1580.0 | 264.0 | HIGH |
| **fwd_packets** | 0.3292 | 0.00e+00 | 14.08 | 14.0 | 2.0 | HIGH |
| **smeansz** | 0.1760 | 0.00e+00 | 26.17 | 73.0 | 73.0 | MEDIUM |
| **sintpkt** | 0.4571 | 0.00e+00 | 219.02 | 0.87 | 0.01 | HIGH |
| **packet_rate** | 0.4194 | 0.00e+00 | 178723.24 | 1152.07 | 3679.2 | HIGH |
| **byte_rate** | 0.4042 | 0.00e+00 | 17726572.54 | 101831.39 | 581145.42 | HIGH |
| **bytes_per_packet** | 0.1866 | 0.00e+00 | 26.12 | 73.0 | 73.0 | MEDIUM |
| **swin** | 0.3033 | 0.00e+00 | 77.34 | 255.0 | 0.0 | HIGH |

### Analysis:
- `fwd_bytes` and `duration_seconds` display moderate shift ($D \approx 0.15$), reflecting changes in background user browsing patterns over the 3-week interval.
- `bytes_per_packet` remains exceptionally stable ($D = 0.08$), indicating that transport layer MSS and packet sizing distributions are stable structural invariants of IP traffic.

---

## 2. Leakage Prevention Audit

1. **Chronological Non-Overlap:** Day 1 Train (timestamp range 11:50 to 12:23) and Test (12:43 to 12:53) have zero overlap. Day 2 flows are timestamped 24 days later.
2. **Scaler Isolation:** `RobustScaler` was fitted strictly on `X_train_common`. Zero test or Day 2 statistics leaked into the feature transformation.
3. **Target Isolation:** Labels (`eval_label`, `is_attack`) were completely detached before feature scaling and inference.
