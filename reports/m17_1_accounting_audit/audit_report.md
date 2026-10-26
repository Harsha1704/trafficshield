# TrafficShield M17.1 — Accounting Invariant Audit & Memory Criteria Report

**Document ID:** TS-M17.1-AUDIT  
**Date:** 2026-10-26  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Milestone:** M17.1 Accounting Invariant Audit, Memory Criteria, and Git Push  
**Expected Starting Commit:** `da5d476`  
**Current Gate Verdict:** **`READY FOR LOCAL DEMONSTRATION`** (Maintained)  

---

## 1. Executive Summary & Defect Findings

Milestone 17.1 performed a forensic counter-semantics audit of TrafficShield's real-time detection pipeline, the M17 soak test harness, and host resource telemetry collectors.

### 1.1 Invariant & Counter Defects Identified & Corrected:
1. **Ambiguous `flows_queued` Counter Semantics:**
   - *Previous state:* Ambiguity existed as to whether `flows_queued` counted enqueue attempts or accepted queue items.
   - *Audit finding:* In `streaming/manager.py`, `flows_queued += 1` occurs strictly **after** `flow_queue.put(f, timeout=1.0)` succeeds. When the queue is saturated, `flows_queue_dropped += 1` increments and `flows_queued` is untouched.
   - *Resolution:* Clarified that `flows_queued` means **successfully accepted queue items**. Total enqueue attempts are `flows_queued + flows_queue_dropped`. The conservation equation `flows_completed == flows_queued + flows_queue_dropped` was proven and enforced.
2. **Missing `alerts_deduplicated` and `alerts_unpersisted_no_app` Telemetry Counters:**
   - *Previous state:* `StreamingInferenceWorker._persist_alert()` dropped duplicate alerts within the 10-second deduplication window via silent `return`, and skipped persistence when `self.app is None` without counting. Consequently, `INV_6` could only evaluate a loose inequality (`persisted + failed <= anomalies`).
   - *Audit finding:* An alert deduplicated before DB submission is mutually exclusive from persistence failure. An alert dropped because no Flask DB context was passed was unaccounted for.
   - *Resolution:* Added `alerts_deduplicated` and `alerts_unpersisted_no_app` counters to `StreamingInferenceWorker` and exposed them via `get_metrics()`. Now, alert persistence obeys an **exact equality invariant**:
     $$\text{anomalies\_detected} == \text{alerts\_persisted} + \text{persistence\_failures} + \text{alerts\_deduplicated} + \text{alerts\_unpersisted\_no_app}$$
3. **Scoring Outcome Isolation:**
   - *Previous state:* `_score_flow()` invoked `self.service.predict_single(flow)` and telemetry inside the same broad `try` block, creating a theoretical risk where a failure during telemetry or persistence could double-count a scored flow as an `inference_failure`.
   - *Resolution:* Model inference was isolated into its own dedicated `try/except`. If `predict_single` succeeds, `flows_scored += 1` increments immediately and cannot be overridden by subsequent downstream errors.
4. **Ambiguous Memory Drift Stability Criteria:**
   - *Previous state:* Described informally as `< 250 MB or < 50%` without specifying whether it was absolute, relative, cold-start, or post-warmup.
   - *Audit finding:* When baseline memory was sampled before model loading, the cold Python interpreter jumped ~135 MB upon initial XGBoost/Scapy unpickling, causing a 62.9% relative increase even though the absolute growth was well within safe operational limits.
   - *Resolution:* Implemented a formal `MemoryStabilityPolicy` with configurable rule modes (`OR`, `AND`, `ABSOLUTE_ONLY`, `RELATIVE_ONLY`), a 50 MB low-baseline headroom floor, and explicit component warmup in the harness.
5. **Silent Zero Resource Readings:**
   - *Previous state:* When Windows PSAPI or psutil failed, `ResourceSnapshot` returned `0.0 MB` and `0.0% CPU`.
   - *Resolution:* Modified `ResourceSnapshot` to return `None` with `is_available: False` and explicit `error_message`, preventing false claims of zero memory or CPU usage.

---

## 2. Comprehensive Pipeline Counter Semantics & Source Locations

| Counter Name | Source Location | Exact Semantic Meaning | Mutually Exclusive Stage |
| :--- | :--- | :--- | :--- |
| `packets_read` / `packets_captured` | `pcap_source.py:274`, `live_source.py:334` | Count of **valid IPv4 packets** yielded to pipeline. | Stage 0 (Packet Input) |
| `malformed_packets` | `packet_validator.py`, `pcap_source.py:182` | Packets rejected due to header/checksum violations. | Stage 0 (Packet Input) |
| `truncated_packets` | `packet_validator.py`, `pcap_source.py:184` | Packets rejected due to length < IP total length. | Stage 0 (Packet Input) |
| `unsupported_packets` | `pcap_source.py:174`, `live_source.py:248` | Non-IPv4 packets (ARP, IPv6, LLDP, etc.). | Stage 0 (Packet Input) |
| `packets_processed` | `flow_builder.py:177` | Valid packet envelopes received by the flow builder. | Stage 1 (Flow Reconstruction) |
| `flows_created` | `flow_builder.py:209` | Unique 5-tuple flow entries initialized in state table. | Stage 1 (Flow Reconstruction) |
| `flows_completed` | `flow_builder.py:219, 232, 243, 255` | Flows finalized and evicted from state table. | Stage 1 (Flow Reconstruction) |
| `flows_closed_tcp` | `flow_builder.py:220` | Flows finalized by TCP FIN/RST or max lifetime (60s). | Stage 1 (Flow Reconstruction) |
| `flows_expired_timeout`| `flow_builder.py:233` | Flows finalized due to idle gap exceeding 2.0s. | Stage 1 (Flow Reconstruction) |
| `flows_evicted_overflow`| `flow_builder.py:244` | Oldest flow evicted when state table reaches 10,000 cap. | Stage 1 (Flow Reconstruction) |
| `flows_flushed` | `flow_builder.py:256` | Active in-flight flows evacuated during session shutdown. | Stage 1 (Flow Reconstruction) |
| `flows_queued` | `manager.py:316, 358, 372` | Completed flows **successfully accepted** into `flow_queue`. | Stage 2 (Queue Ingestion) |
| `flows_queue_dropped` | `manager.py:318, 360, 374` | Completed flows dropped due to queue saturation (`queue.Full`). | Stage 2 (Queue Ingestion) |
| `flows_scored` | `inference_worker.py:247` | Flows dequeued and successfully evaluated by XGBoost. | Stage 3 (Terminal Worker Scoring) |
| `incompatible_flows_rejected` | `inference_worker.py:233` | Flows dequeued but rejected (e.g. invalid STTL <= 0). | Stage 3 (Terminal Worker Scoring) |
| `validation_errors` | `inference_worker.py:241` | Flows failing preprocessor schema (`ValueError`/`KeyError`).| Stage 3 (Terminal Worker Scoring) |
| `inference_failures` | `inference_worker.py:243` | Flows failing model inference runtime unexpectedly. | Stage 3 (Terminal Worker Scoring) |
| `unprocessed_flows` | `inference_worker.py:185` | Flows remaining on queue when shutdown drain timeout expires.| Stage 3 (Terminal Worker Scoring) |
| `anomalies_detected` | `inference_worker.py:257` | Flows scored with $\text{anomaly\_score} \ge \tau$ (0.50). | Stage 4 (Alert Lifecycle) |
| `alerts_persisted` | `inference_worker.py:349` | Unique anomalies committed to SQLite/PostgreSQL DB. | Stage 4 (Alert Lifecycle) |
| `persistence_failures` | `inference_worker.py:351` | Anomalies failing DB commit (rollback executed). | Stage 4 (Alert Lifecycle) |
| `alerts_deduplicated` | `inference_worker.py:307` | Anomalies suppressed by 10.0s 5-tuple deduplication cache. | Stage 4 (Alert Lifecycle) |
| `alerts_unpersisted_no_app` | `inference_worker.py:299` | Anomalies detected in standalone mode (no Flask app). | Stage 4 (Alert Lifecycle) |

---

## 3. Mathematical Accounting Invariants & Lifecycle Partition

### 3.1 Stage 1: Packet Ingestion Invariant
$$\text{packets\_total} = \text{packets\_valid} + \text{packets\_dropped} + \sum \text{packets\_rejected}$$
Where:
- $\text{packets\_valid} = \text{packets\_read}$ (PCAP) or $\text{packets\_captured}$ (Live)
- $\sum \text{packets\_rejected} = \text{malformed} + \text{truncated} + \text{unsupported}$

### 3.2 Stage 2: Flow Reconstruction Conservation
$$\text{flows\_created} = \text{flows\_completed} + \text{active\_flows\_count}$$
At clean shutdown after `flush()`, $\text{active\_flows\_count} = 0 \implies \text{flows\_created} == \text{flows\_completed}$.
And the completed flows decompose into exactly 4 mutually exclusive finalization conditions:
$$\text{flows\_completed} = \text{flows\_expired\_timeout} + \text{flows\_closed\_tcp} + \text{flows\_evicted\_overflow} + \text{flows\_flushed}$$

### 3.3 Stage 3: Queue Ingestion Conservation
Completed flows are offered to `flow_queue`:
$$\text{flows\_completed} = \text{flows\_queued} + \text{flows\_queue\_dropped}$$
Where $\text{flows\_queued}$ counts only accepted items.

### 3.4 Stage 4: Mutually Exclusive Terminal Scoring Partition
Every flow accepted into `flow_queue` receives **exactly one terminal outcome**:
$$\text{flows\_queued} = \text{flows\_scored} + \text{incompatible\_flows\_rejected} + \text{validation\_errors} + \text{inference\_failures} + \text{unprocessed\_flows}$$

### 3.5 Stage 5: Alert Persistence Lifecycle Conservation
For all detected anomalies ($\text{anomaly\_score} \ge 0.50$):
$$\text{anomalies\_detected} = \text{alerts\_persisted} + \text{persistence\_failures} + \text{alerts\_deduplicated} + \text{alerts\_unpersisted\_no_app}$$
- $\text{alerts\_deduplicated}$ and $\text{persistence\_failures}$ are strictly mutually exclusive because deduplication check precedes database persistence attempt.

---

## 4. Memory Stability Acceptance Criteria & Semantics

### 4.1 Specification
Implemented in `tools/soak/memory_policy.py` as `MemoryStabilityPolicy`:
- `max_absolute_growth_mb: float = 250.0`
- `max_relative_growth_pct: float = 50.0`
- `min_absolute_headroom_mb: float = 50.0`
- `rule_mode: str = "OR"` (Supports `"OR"`, `"AND"`, `"ABSOLUTE_ONLY"`, `"RELATIVE_ONLY"`)
- `is_provisional: bool = True` (Proposed criteria subject to operational review)

### 4.2 Engineering Rationale
1. **Warmup vs Steady-State:** Initial ML library and model import consumes ~135 MB of physical RAM. Baseline RSS is sampled post-warmup to measure actual runtime leakage rather than cold-start module loading.
2. **Headroom Floor (50 MB):** Prevents false failures on small baselines (e.g. 20 MB growing to 45 MB is a 125% relative increase, but only 25 MB absolute).
3. **Hard Absolute Ceiling (250 MB):** Prevents large baselines from unbounded growth (e.g. 600 MB baseline growing to 860 MB is only 43% relative, but breaches the 250 MB ceiling).

---

## 5. Test Verification Summary

- **M17.1 Dedicated Unit Tests:** `tests/unit/test_m17_1_accounting_audit.py` $\to$ **14 / 14 passed** in 0.58s.
- **M17 Soak Harness Unit Tests:** `tests/unit/test_m17_soak_harness.py` $\to$ **10 / 10 passed** in 3.92s.
- **Full Backend Pytest Regression:** All backend tests verified passing.
- **Static Analysis (Ruff):** Clean, 0 errors across entire repository.
- **Static Typing (Mypy):** Clean, 0 errors across 48 source files.
- **Model Hashes:**
  - `production_detector.joblib`: `c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495` (Verified)
  - `production_preprocessor.joblib`: `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653` (Verified)

---

## 6. Release Gate Conclusion

The accounting invariant reconciliation, memory acceptance criteria, and resource telemetry error surfacing are fully verified. In accordance with release protocol, the release gate remains strictly:

**`READY FOR LOCAL DEMONSTRATION`**
