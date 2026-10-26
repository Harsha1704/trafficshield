# TrafficShield M15.4 — Formal Flow Accounting Model & Invariants

**Document ID:** TS-M15.4-ACCOUNTING  
**Date:** 2026-10-26  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Milestone:** M15.4 Shutdown Edge-Case Verification & Concurrency Hardening  

---

## 1. Executive Summary

Milestone 15.4 audited and mathematically defined the complete operational flow accounting model across the entire ingestion, builder, queue, scoring, and persistence lifecycles.

A critical design distinction established in this audit is that **flow scoring outcomes** and **alert persistence outcomes** operate at two different stages of the detection pipeline. Conflating these two stages would introduce double-counting whenever an alert fails to commit to the database after scoring has succeeded.

---

## 2. Mathematical Accounting Invariants

### 2.1 Stage 1: Flow Reconstruction Engine (`UnidirectionalFlowBuilder`)

At any arbitrary instant during packet processing:
$$\text{flows\_created} = \text{flows\_completed} + |\text{active\_flows}|$$

At final shutdown teardown, after `builder.flush()` has evacuated all remaining in-flight flows:
$$|\text{active\_flows}| = 0 \implies \text{flows\_created} = \text{flows\_completed}$$

For all completed flows, finalization occurs via exactly one of four mutually exclusive conditions:
$$\text{flows\_completed} = \text{flows\_expired\_timeout} + \text{flows\_closed\_tcp} + \text{flows\_evicted\_overflow} + \text{flows\_flushed}$$

Where:
- $\text{flows\_expired\_timeout}$: Flows idle for $> 2.0$ seconds.
- $\text{flows\_closed\_tcp}$: Flows finalized upon TCP FIN/RST flags or maximum flow lifetime limit ($> 60.0$ seconds).
- $\text{flows\_evicted\_overflow}$: Least-recently updated flows evicted when the state table reaches its cap ($10,000$ flows).
- $\text{flows\_flushed}$: Active in-flight flows flushed at session shutdown or replay EOF.

---

### 2.2 Stage 2: Queue Ingestion (`RealTimeDetectionManager`)

Finalized flows from the flow builder are inserted into `flow_queue`. Under queue saturation, completed flows that cannot be enqueued within the put timeout are dropped:
$$\text{flows\_queued} = \text{flows\_completed} - \text{flows\_queue\_dropped}$$

Under normal operating conditions where queue capacity ($10,000$) accommodates bursts:
$$\text{flows\_queue\_dropped} = 0 \implies \text{flows\_queued} = \text{flows\_completed}$$

---

### 2.3 Stage 3: Terminal Flow Scoring Outcomes (`StreamingInferenceWorker`)

Every flow that enters `flow_queue` receives **exactly one terminal scoring outcome**:
$$\text{flows\_queued} = \text{flows\_scored} + \text{incompatible\_flows\_rejected} + \text{validation\_errors} + \text{inference\_failures} + \text{unprocessed\_flows}$$

#### Mutually Exclusive Category Definitions:
1. $\text{flows\_scored}$: Flow was dequeued and successfully evaluated by the frozen `ProductionInferenceService` (producing an anomaly score and explanation).
2. $\text{incompatible\_flows\_rejected}$: Flow was dequeued but rejected prior to inference because it violated model compatibility (e.g. invalid STTL, unsupported protocol).
3. $\text{validation\_errors}$: Flow was dequeued, but preprocessor feature schema validation failed (`ValueError`, `KeyError`).
4. $\text{inference\_failures}$: Flow was dequeued, but model execution failed due to an unexpected runtime exception.
5. $\text{unprocessed\_flows}$: Flow was enqueued, but remained in `flow_queue` when the shutdown drain timeout expired.

---

### 2.4 Stage 4: Alert Persistence Lifecycle (`StreamingInferenceWorker._persist_alert`)

Alert persistence is a downstream action triggered **only** for flows where $\text{flows\_scored}$ produced an anomaly ($\text{score} \ge \tau$):
$$\text{flows\_scored} = \text{benign\_flows} + \text{anomalies\_detected}$$

For all detected anomalies:
$$\text{anomalies\_detected} = \text{alerts\_persisted} + \text{persistence\_failures} + \text{alerts\_deduplicated}$$

Where:
- $\text{alerts\_persisted}$: Successfully committed as `SecurityAlert` in the database.
- $\text{persistence\_failures}$: Database commit or connection failure (`OperationalError`, `IntegrityError`). The flow is still counted as $\text{flows\_scored}$ because model inference succeeded and generated real-time telemetry.
- $\text{alerts\_deduplicated}$: Suppressed from redundant database writes by the 10.0-second sliding-window deduplication cache.

---

## 3. Reconciliation Matrix from Test 12

In `tests/unit/test_m15_4_shutdown_edge_cases.py::test_12_exact_final_accounting_comprehensive`:

| Lifecycle Stage | Metric Name | Value | Invariant Check | Status |
|:---|:---|:---:|:---|:---:|
| **Queue Input** | `flows_queued` | 5 | Input baseline | — |
| **Terminal Outcome 1** | `flows_scored` | 2 | Scored by XGBoost | **VERIFIED** |
| **Terminal Outcome 2** | `incompatible_flows_rejected` | 1 | Incompatible STTL | **VERIFIED** |
| **Terminal Outcome 3** | `validation_errors` | 1 | Bad feature schema | **VERIFIED** |
| **Terminal Outcome 4** | `inference_failures` | 1 | Model runtime error | **VERIFIED** |
| **Terminal Outcome 5** | `unprocessed_flows` | 0 | Drain completed | **VERIFIED** |
| **Sum of Outcomes** | $\sum \text{Outcomes}$ | **5** | Exactly matches `flows_queued` ($5 == 5$) | **PASS** |
