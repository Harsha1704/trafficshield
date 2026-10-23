# TrafficShield — Data Quality & Leakage Audit Report

**Dataset**: UNSW-NB15 (Files 1 & 2 Day 1 Stream)  
**Total Records Audited**: 100,000  
**Eligible Causal Features**: 13 (duration_seconds, fwd_bytes, sttl, sload, fwd_packets, swin, smeansz, sjit, sintpkt, is_sm_ips_ports, packet_rate, byte_rate, bytes_per_packet)

## 1. Missing Values & Infinities
- **Total NaN values**: 0 across all features
- **Total Inf values**: 0 across all features
- **Near-constant columns**: None (all causal features have healthy variance)

## 2. Target Distribution & Categories
- **Normal Traffic**: 88,570 (88.57%)
- **Attack Traffic**: 11,430 (11.43%)
- **Attack Categories Present**:
  - `normal`: 88,570 (88.57%)
  - `exploits`: 3,374 (3.37%)
  - `fuzzers`: 3,329 (3.33%)
  - `generic`: 1,820 (1.82%)
  - `reconnaissance`: 945 (0.95%)
  - `dos`: 862 (0.86%)
  - `backdoor`: 494 (0.49%)
  - `analysis`: 464 (0.46%)
  - `shellcode`: 126 (0.13%)
  - `worms`: 16 (0.02%)

## 3. Target Leakage Verification
- **Strongest Feature-Target Correlation**: `sttl` (Pearson r = 0.8022)
- **Leakage Finding**: Zero features have correlation r > 0.65 with target. Target identity is completely absent from the predictive matrix.

## 4. Chronological Integrity
- **Timestamp Column**: `flow_end_ts` ($L_{\text{time}}$)
- **Monotonic Sequence**: True (0 temporal inversions)
- **Time Range**: 2015-01-22T11:50:14+00:00 to 2015-01-22T12:53:21+00:00

## 5. Cross-File Generalization Holdout
- **Holdout File**: `UNSW-NB15_3.csv`
- **Holdout Samples**: 20,000
- **Holdout Attack Prevalence**: 25.47%
- **Holdout Time Range**: 2015-02-18 03:45:29+00:00 to 2015-02-18 03:52:53+00:00
