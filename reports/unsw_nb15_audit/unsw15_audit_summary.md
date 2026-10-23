# TrafficShield — UNSW-NB15 Dataset Audit Report

**Audit Timestamp:** 2026-10-23T07:06:49.430401+00:00  
**Source Directory:** `D:\projects\trafficshield\datasets\raw\unsw_nb15`  
**Total Records Audited:** 2,540,047  
**Valid Records:** 2,540,047 (100.0%)  
**Malformed/Rejected:** 0  

## 1. Dataset Row-Count Discrepancy Investigation & Resolution

- **Raw Physical Rows Counted:** 2,540,047
- **Boundary Duplicate Rows Identified:** 3
- **Unique Records After Boundary Deduplication:** 2,540,044
- **Official Published UNSW-NB15 Total:** 2,540,044
- **Discrepancy Status:** ✅ Fully Resolved

### Empirical Evidence & Explanation

The original creators partitioned the master UNSW-NB15 dataset into four CSV files with inclusive 1-row boundary overlaps:
1. **UNSW-NB15_1.csv -> UNSW-NB15_2.csv:** Row 700,001 of File 1 is byte-for-byte identical to Row 1 of File 2.
2. **UNSW-NB15_2.csv -> UNSW-NB15_3.csv:** Row 700,001 of File 2 is byte-for-byte identical to Row 1 of File 3.
3. **UNSW-NB15_3.csv -> UNSW-NB15_4.csv:** Row 700,001 of File 3 is byte-for-byte identical to Row 1 of File 4.

$$2,540,047 \text{ raw rows} - 3 \text{ boundary duplicate rows} = 2,540,044 \text{ unique records}$$
This completely explains the 3-row discrepancy between physical file lines and published totals.

## 2. Global Chronological Ordering & Timestamp Analysis

| Filename | Size (MB) | Rows Audited | Valid Rows | Monotonic Ltime? | Ltime Start (UTC) | Ltime End (UTC) |
|---|---|---|---|---|---|---|
| `UNSW-NB15_1.csv` | 161.15 | 700,001 | 700,001 | ✅ Yes (0 drops) | 2015-01-22T11:50:14+00:00 | 2015-01-22T19:44:02+00:00 |
| `UNSW-NB15_2.csv` | 157.57 | 700,001 | 700,001 | ✅ Yes (0 drops) | 2015-01-22T19:44:02+00:00 | 2015-02-18T03:45:29+00:00 |
| `UNSW-NB15_3.csv` | 147.43 | 700,001 | 700,001 | ✅ Yes (0 drops) | 2015-02-18T03:45:29+00:00 | 2015-02-18T09:00:09+00:00 |
| `UNSW-NB15_4.csv` | 93.07 | 440,044 | 440,044 | ✅ Yes (0 drops) | 2015-02-18T09:00:09+00:00 | 2015-02-18T12:21:09+00:00 |

### Resolution of Cross-File Timestamp Overlap
- **Global Ltime Monotonicity Violations:** 0 drops across the concatenated sequence.
- **Stime vs Ltime Semantics:** Flows are sorted globally by `Ltime` (flow end timestamp). `Stime` is the flow start timestamp ($S_{\text{time}} = L_{\text{time}} - \text{dur}$).
- For boundary flows with positive duration, `Stime` naturally precedes `Ltime`. Comparing `min(Stime)` of a subsequent file to `max(Ltime)` of the preceding file gave a false impression of an overlap, whereas `Ltime` is monotonically ordered across all files.

## 3. Reconciled 49-Column Feature Policy Accounting

The complete 49-field UNSW-NB15 schema forms an exact, disjoint partition into 5 categories:

| Category | Column Count | Status | Notes |
|---|---|---|---|
| `forward_observable_numeric` | 19 | ✅ Eligible | 10 per-flow intrinsic + 9 batch window aggregates |
| `forward_observable_metadata` | 4 | ℹ️ Encoded | Ports/protocols (`sport`, `dsport`, `proto`, `service`) |
| `reverse_direction` | 13 | ❌ Prohibited | Return bytes, packets, jitter, load, TTL, TCP window |
| `bidirectional_or_future_dependent` | 6 | ❌ Prohibited | Handshake state, loss, transaction depth, FTP login |
| `identifier_or_grouping_only` | 7 | ⛔ Excluded | IPs (`srcip`, `dstip`), `stcpb`, timestamps (`Stime`, `Ltime`), targets (`attack_cat`, `Label`) |
| **Total** | **49** | | **Exact disjoint partition of all 49 fields** |

> **Note on Previous '24 Prohibited' Count:** The prior audit report grouped 13 reverse + 6 bidirectional (= 19 prohibited directional features) plus 5 identifiers/labels (= 24 non-feature columns), omitting `Stime` and `Ltime` (2 timestamps). The reconciled partition accounts for all 7 non-feature columns ($19 + 4 + 13 + 6 + 7 = 49$).

## 4. Causal Observability Audit of Model Features

- **10 Strictly Causal Per-Flow Features:** `dur`, `sbytes`, `sttl`, `sload`, `spkts`, `swin`, `smeansz`, `sjit`, `sintpkt`, `is_sm_ips_ports`. Measurable online from forward packet stream with zero lookahead.
- **9 Precomputed Batch Window Aggregates (ct_*):** `ct_flw_http_mthd`, `ct_ftp_cmd`, `ct_srv_src`, `ct_srv_dst`, `ct_dst_ltm`, `ct_src_ltm`, `ct_src_dport_ltm`, `ct_dst_sport_ltm`, `ct_dst_src_ltm`. Precomputed over 100-connection windows containing future observations (e.g. Row 0 has `ct_srv_src = 3`, counting Rows 27 and 37). Excluded from strict causal one-way detection.

## 5. Label and Attack Category Distribution

- **Normal / Benign (0):** 2,218,764 flows (87.35%)
- **Attack (1):** 321,283 flows (12.6487%)

| Category | Flow Count | Share (%) |
|---|---|---|
| `normal` | 2,218,764 | 87.3513% |
| `exploits` | 44,525 | 1.7529% |
| `reconnaissance` | 13,987 | 0.5507% |
| `dos` | 16,353 | 0.6438% |
| `generic` | 215,481 | 8.4833% |
| `shellcode` | 1,511 | 0.0595% |
| `fuzzers` | 24,246 | 0.9545% |
| `worms` | 174 | 0.0069% |
| `backdoor` | 2,329 | 0.0917% |
| `analysis` | 2,677 | 0.1054% |

## 6. Evaluation Feasibility Findings

1. **Headerless Format Verified:** All data files strictly lack headers and adhere to the 49-field UNSW-NB15 schema contract.
2. **Strict Chronological Ordering:** Flows inside each file and across files 1–4 are ordered by `Ltime` (flow end timestamp).
3. **Zero Reverse Leakage:** All 13 reverse features and 6 bidirectional/future features are mapped out of model training.
4. **Causal Integrity:** Strict causal mode restricts model features to the 10 per-flow intrinsic forward observables, avoiding future-flow lookahead in batch window aggregates.
