# TrafficShield M15.2 — Flow Accounting & Reconciliation Specification

**Document ID:** TS-M15.2-ACCOUNTING  
**Date:** 2026-10-26  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Scope:** Mathematical specification of the flow accounting model, mutually exclusive counter definitions, and reconciliation proofs.

---

## 1. Flow Accounting Model

TrafficShield tracks flows across their entire lifecycle from wire packet arrival through inference and alert persistence. The accounting model guarantees that every constructed flow belongs to exactly one terminal state.

### Authoritative Counters

| Component | Counter Name | Semantic Definition |
|:---|:---|:---|
| **Flow Builder** | `flows_created` | Total unique 5-tuple flow states instantiated upon arrival of new unidirectional packets. |
| **Flow Builder** | `flows_completed` | Total flow states finalized and emitted by the builder via timeout, TCP FIN/RST, capacity eviction, or flush. |
| **Flow Builder** | `flows_expired_timeout` | Flows finalized due to reaching the idle timeout ($\Delta t > 2.0\text{ s}$). |
| **Flow Builder** | `flows_closed_tcp` | Flows finalized immediately upon observing a TCP packet with `FIN` or `RST` flag set, or max lifetime exceeded. |
| **Flow Builder** | `flows_evicted_overflow`| Flows evicted prematurely from active table due to reaching capacity bound (`max_active_flows = 10,000`). |
| **Flow Builder** | `flows_flushed` | Flows finalized and extracted at session termination via `flow_builder.flush()`. |
| **Flow Builder** | `active_flows_count` | In-flight active flow states currently maintained in builder memory. |
| **Manager** | `flows_queued` | Total finalized flows successfully enqueued into `flow_queue`. |
| **Manager** | `flows_queue_dropped` | Finalized flows dropped because `flow_queue` reached capacity (`maxsize = 10,000`). |
| **Inference Worker** | `flows_scored` | Completed flows successfully transformed and evaluated by the frozen XGBoost detector. |
| **Inference Worker** | `incompatible_flows_rejected` | Completed flows rejected prior to model scoring due to policy failure (e.g. $sttl \le 0$ or corrupt header). |
| **Inference Worker** | `validation_errors` | Completed flows that encountered runtime exceptions during feature preparation or prediction. |
| **Inference Worker** | `unprocessed_flows` | Completed flows remaining in queue that were discarded due to drain timeout expiration or force halt. |
| **Alert Engine** | `anomalies_detected` | Scored flows where continuous model score $P(\text{anomaly}) \ge \tau$ ($\tau = 0.50$). |
| **Alert Engine** | `alerts_persisted` | Unique security alert records committed to the database after 10-second deduplication. |

---

## 2. Mathematical Reconciliation Invariants

The accounting model enforces the following mathematical equalities:

### Invariant 1: Flow Completion Conservation
At all times (before flush):
$$\text{flows\_created} = \text{active\_flows\_count} + \text{flows\_completed}$$

After graceful shutdown (`flush()` executed):
$$\text{active\_flows\_count} = 0$$
$$\text{flows\_created} = \text{flows\_completed}$$
$$\text{flows\_completed} = \text{flows\_expired\_timeout} + \text{flows\_closed\_tcp} + \text{flows\_evicted\_overflow} + \text{flows\_flushed}$$

### Invariant 2: Queue Ingestion Conservation
$$\text{flows\_queued} = \text{flows\_completed} - \text{flows\_queue\_dropped}$$

Under normal operations where queue bounds are respected ($\text{flows\_queue\_dropped} = 0$):
$$\text{flows\_queued} = \text{flows\_completed}$$

### Invariant 3: Inference Terminal Conservation
Every queued flow must be accounted for by the inference worker across mutually exclusive categories:
$$\text{flows\_queued} = \text{flows\_scored} + \text{incompatible\_flows\_rejected} + \text{validation\_errors} + \text{unprocessed\_flows}$$

---

## 3. Reconciliation of Milestone 15.1 Live Capture Run

Applying this accounting framework to the M15.1 live Wi-Fi capture telemetry ($T = 24.1\text{ s}$):

| Stage | Metric Name | M15.1 Value | Audit Explanation |
|:---|:---|:---:|:---|
| **Builder** | `flows_created` | **757** | Ambient Wi-Fi flows built from 8,259 wire packets. |
| **Builder** | `flows_completed` | **757** | All flows finalized (including in-flight flows at stop). |
| **Builder** | `flows_flushed` | **89** | In-flight active flows extracted during `stop()`. |
| **Builder** | `active_flows_count` | **0** | All flows evacuated from memory at stop. |
| **Manager** | `flows_queued` | **757** | 668 during capture + 89 at shutdown flush. |
| **Worker** | `flows_scored` | **668** | Flows evaluated by frozen XGBoost before stop signal halted worker. |
| **Worker** | `incompatible_flows_rejected` | **0** | Zero corrupt or non-positive TTL flows. |
| **Worker** | `validation_errors` | **0** | Zero schema or prediction exceptions. |
| **Worker** | `unprocessed_flows` (prior implementation) | **89** | Flows stranded in queue due to premature worker loop termination. |
| **Alerts** | `anomalies_detected` | **431** | Flows scored $\ge 0.50$ (attributed to domain TTL shift). |
| **Alerts** | `alerts_persisted` | **241** | Deduplicated across 10-second window ($431 - 190 = 241$). |

### Reconciliation Check:
$$\text{flows\_queued} = \text{flows\_scored} + \text{unprocessed\_flows}$$
$$757 = 668 + 89 \quad \checkmark$$

---

## 4. Milestone 15.2 Graceful Drain Guarantee

With the M15.2 orderly shutdown sequence implemented:
- When `stop(drain_timeout=5.0)` is called, the inference worker **processes all 89 flushed flows** up to the sentinel `None`.
- Under normal operational shutdown without drain timeout breach:
  $$\text{unprocessed\_flows} = 0$$
  $$\text{flows\_scored} = \text{flows\_queued} = \text{flows\_completed} = \text{flows\_created}$$
- If an operator specifies an ultra-short timeout or emergency abort occurs, any unconsumed flows are popped and added to `unprocessed_flows`, ensuring **zero silent omissions** in SOC telemetry.
