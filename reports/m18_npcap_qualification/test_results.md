# TrafficShield M18 — Native Statistics Test Results & Verification

**Document ID:** TS-M18-TEST-REPORT  
**Date:** 2026-10-26  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Milestone:** M18 Memory Policy Review & Native Npcap Statistics  
**Test Suite:** `tests/unit/test_m18_native_stats.py` & `tests/unit/test_m17_1_accounting_audit.py`  
**Execution Environment:** Windows 11 / Python 3.14.8  

---

## 1. Executive Summary

Milestone 18 introduces 10 deterministic unit tests covering native driver statistics collection, interval delta computation, counter reset detection, error isolation, and tiered drop demarcation. All 10 tests passed in 0.63s without initiating real network sniffing.

Combined with 15 memory policy tests in `test_m17_1_accounting_audit.py` and 10 soak harness tests in `test_m17_soak_harness.py`, 35 milestone-specific unit tests passed with 100% success.

---

## 2. Detailed Test Matrix for `test_m18_native_stats.py`

| Test ID | Test Function | Purpose / Scenarios Tested | Execution Time | Result |
| :--- | :--- | :--- | :---: | :---: |
| **TEST_1** | `test_1_successful_statistics_retrieval_and_mapping` | Verified `ps_recv`, `ps_drop`, `ps_ifdrop` mapping and initial delta. | 0.04s | **PASS** |
| **TEST_2** | `test_2_cumulative_counter_interval_deltas` | Verified successive poll deltas (e.g. $+500$ packets, $+5$ drops). | 0.05s | **PASS** |
| **TEST_3** | `test_3_unsupported_capture_source_pcap_replay` | Verified PCAP replay returns `UNSUPPORTED_SOURCE` and `None` drops. | 0.06s | **PASS** |
| **TEST_4** | `test_4_missing_or_invalid_handle_reports_unavailable` | Verified polling with `None` handle returns `is_available: False`. | 0.04s | **PASS** |
| **TEST_5** | `test_5_native_api_error_handling` | Verified simulated `wpcap.dll` access violation is caught safely. | 0.04s | **PASS** |
| **TEST_6** | `test_6_counter_reset_or_decrease_handling` | Verified driver ring buffer reset is flagged and delta protected. | 0.04s | **PASS** |
| **TEST_7** | `test_7_statistics_unavailable_never_substitutes_zero` | Verified unavailable stats return `None`, never false zero. | 0.04s | **PASS** |
| **TEST_8** | `test_8_tiered_drop_demarcation_isolation` | Verified kernel drops, ingestion drops, and flow drops remain distinct. | 0.05s | **PASS** |
| **TEST_9** | `test_9_repeated_polling_interval_timing` | Verified `poll_interval_seconds` is recorded across interval polls. | 0.04s | **PASS** |
| **TEST_10**| `test_10_adapter_reset` | Verified `reset()` clears historical cumulative counters. | 0.04s | **PASS** |

---

## 3. Memory Policy Test Verification Matrix

All 15 tests in `tests/unit/test_m17_1_accounting_audit.py` passed in 0.63s:
- **`test_policy_normal_bounded_growth`:** Baseline 120 MB $\to$ 150 MB (PASS).
- **`test_policy_low_baseline_with_small_absolute_growth`:** Baseline 20 MB $\to$ 50 MB protected by headroom (PASS).
- **`test_policy_low_baseline_excessive_absolute_growth`:** Baseline 20 MB $\to$ 300 MB fails hard ceiling (PASS).
- **`test_policy_normal_baseline_excessive_relative_growth_under_and`:** Baseline 100 MB $\to$ 180 MB fails under AND mode (PASS).
- **`test_policy_high_baseline_excessive_absolute_growth`:** Baseline 600 MB $\to$ 860 MB fails under AND mode (PASS).
- **`test_policy_growth_over_both_limits_fails_all_modes`:** Baseline 200 MB $\to$ 500 MB fails in all modes (PASS).
- **`test_policy_exact_boundary_values`:** Delta 250.00 MB passes, 250.01 MB fails (PASS).
- **`test_policy_unavailable_measurements`:** Baseline None or final None fails explicitly (PASS).
- **`test_policy_memory_decrease_passes`:** Memory decrease (OS page reclamation) passes (PASS).

---

## 4. Live Interface Validation Boundary

In strict adherence to project safety rules:
- No real network traffic was sniffed or transmitted during automated test execution.
- Native Npcap driver polling was verified using handle abstractions and mock provider callables.
- Live-interface verification against an active physical NIC (e.g. Realtek RTL8852BE) remains an operational qualification task requiring explicit operator authorization.
