# TrafficShield M15.4 — Failure Injection & Resilience Results

**Document ID:** TS-M15.4-FAIL-INJECT  
**Date:** 2026-10-26  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Milestone:** M15.4 Shutdown Edge-Case Verification & Concurrency Hardening  

---

## 1. Objective & Methodology

Milestone 15.4 applied controlled fault injection across four failure domains to evaluate system resilience and error visibility:
1. **Ingestion Thread Deadlock / Join Timeout**
2. **Worker Inference Loop Drain Timeout**
3. **Model Runtime Execution Crash**
4. **Database Connection / Persistence Failure**
5. **Queue Saturated Backpressure**

---

## 2. Fault Injection Experiments & Observed Behaviors

### Experiment 1: Ingestion Thread Deadlock / Join Timeout
- **Injected Fault:** `BlockedPacketSource` yielded one packet and then blocked indefinitely on a `threading.Event`.
- **System Response:**
  - `RealTimeDetectionManager.stop()` called `_pipeline_thread.join(timeout=...)`.
  - Upon timeout expiration, `self.pipeline_join_timed_out` was set to `True`.
  - State transitioned to `WorkerState.DEGRADED` instead of falsely reporting `STOPPED`.
  - `self.error_message` was set to `"Pipeline thread did not terminate within join timeout"`.
  - `flow_builder.flush()` executed and marked `_is_closed = True`, completely preventing late packet incorporation.
- **Verdict:** **PASS (High Resilience)**.

---

### Experiment 2: Worker Drain Timeout (Slow Scoring)
- **Injected Fault:** `ProductionInferenceService.predict_single` injected with a 50ms per-flow sleep. 20 flows were enqueued, and `worker.stop(drain_timeout=0.05)` was invoked with a 50ms budget.
- **System Response:**
  - Worker drained as many items as possible within 50ms.
  - The drain timer expired; `self.drain_timed_out` and `self.forced_stop` flags were set to `True`.
  - The worker loop broke cleanly.
  - All residual items in `flow_queue` were dequeued, counted into `self.unprocessed_flows`, and `flow_queue.task_done()` was called.
  - No orphaned worker thread remained alive.
  - Conservation invariant held: $\text{flows\_scored} + \text{unprocessed\_flows} = 20$.
- **Verdict:** **PASS (High Resilience)**.

---

### Experiment 3: Model Execution Crash
- **Injected Fault:** `ProductionInferenceService.predict_single` raised an unhandled `RuntimeError("Fatal model inference error")`.
- **System Response:**
  - The exception was caught by `StreamingInferenceWorker._score_flow()`.
  - `self.inference_failures` was incremented from 0 to 2.
  - The worker consumption loop did not crash or terminate; subsequent queued items continued to be processed.
  - `flows_scored` was not incremented for the failing flows.
  - Terminal invariant held: $\text{flows\_queued} = \text{inference\_failures} + \text{flows\_scored}$.
- **Verdict:** **PASS (High Resilience)**.

---

### Experiment 4: Database Persistence Failure
- **Injected Fault:** Injected a mock Flask app context that raised `RuntimeError("Database connection unreachable")` inside `_persist_alert()`.
- **System Response:**
  - `_score_flow()` successfully scored the flow and detected the anomaly ($\tau \ge 0.50$).
  - When calling `_persist_alert()`, the database exception was caught in the try/except block.
  - `db.session.rollback()` was safely attempted.
  - `self.persistence_failures` was incremented from 0 to 1.
  - `self.alerts_persisted` remained 0.
  - `self.flows_scored` remained 1 (the flow was scored; only persistence failed).
- **Verdict:** **PASS (High Resilience)**.

---

### Experiment 5: Saturated Queue Backpressure on Stop
- **Injected Fault:** A bounded queue (`maxsize=4`) was filled to 100% capacity with valid flows before `stop()` was requested.
- **System Response:**
  - `StreamingInferenceWorker.stop()` did not block indefinitely on `flow_queue.put(None)`.
  - The adaptive sentinel insertion loop checked thread liveness and re-attempted insertion with bounded timeouts.
  - As the worker thread consumed items, slots freed up and the sentinel `None` was accepted.
  - All 4 items were scored; zero items dropped or marked unprocessed.
- **Verdict:** **PASS (High Resilience)**.
