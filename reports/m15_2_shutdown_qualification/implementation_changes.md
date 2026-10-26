# TrafficShield M15.2 — Graceful Queue Drain & Orderly Shutdown Implementation

**Document ID:** TS-M15.2-IMPL  
**Date:** 2026-10-26  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Scope:** Architectural and thread-safe implementation of orderly shutdown, queue sentinel draining, flow builder flushing, and comprehensive lifecycle accounting.

---

## 1. Problem Statement: The M15.1 Unscored-Flow Gap

In Milestone 15.1, forensic accounting revealed that during live capture termination, **757 completed flows** were produced by [`UnidirectionalFlowBuilder`](file:///d:/projects/trafficshield/ingestion/flow/flow_builder.py), but only **668 flows** were scored by [`StreamingInferenceWorker`](file:///d:/projects/trafficshield/streaming/inference_worker.py), leaving an unscored gap of **89 flows**.

### Root Cause Analysis of Prior Implementation:
1. When `RealTimeDetectionManager.stop()` was invoked, `self._stop_event.set()` was signaled, and `self.inference_worker.stop()` was immediately called.
2. `self.inference_worker.stop()` put `None` (the sentinel) into the queue and called `self._stop_event.set()`.
3. In `StreamingInferenceWorker._run_loop()`, the loop condition was `while not self._stop_event.is_set():`.
4. As soon as `_stop_event` was set, the worker loop broke out immediately upon finishing whatever single flow was currently being scored, **ignoring the flows that had just been flushed into the queue by `flow_builder.flush()`**.
5. Consequently, 89 active in-flight flows that were flushed at shutdown were left stranded in the queue and never evaluated.

---

## 2. Orderly Shutdown Sequence Design

Milestone 15.2 introduces a strictly ordered, thread-safe, 5-stage shutdown protocol:

```
[ Operator POST /api/v1/capture/stop ]
                  │
                  ▼
         Stage 1: Halt Ingestion
   • Signal manager._stop_event.set()
   • Terminate packet_source.stop()
                  │
                  ▼
         Stage 2: Join Pipeline Thread
   • Join _pipeline_thread (timeout=2.0s)
   • Guarantees NO new packets can enter flow_builder
                  │
                  ▼
         Stage 3: Flush Active Flows
   • Call flow_builder.flush()
   • Enqueue all active flows into flow_queue
   • Increment manager.flows_queued for each flushed flow
                  │
                  ▼
         Stage 4: Graceful Queue Drain
   • Signal worker._drain_requested.set()
   • Put sentinel (None) into flow_queue
   • Worker continues processing all queued flows until None
   • Join worker thread with configurable drain_timeout (default 5.0s)
   • If timeout breached: set worker._stop_event (force halt) and account unprocessed
                  │
                  ▼
         Stage 5: Exact Accounting
   • Count any stranded items in queue: unprocessed_flows
   • Transition state to STOPPED (or COMPLETED if replay EOF)
   • Return complete reconcilable status
```

---

## 3. Concrete Code Changes

### A. `ingestion/flow/flow_builder.py`
- Added explicit counter `self.flows_flushed: int = 0`.
- Incremented `self.flows_flushed += 1` in `flush()`.
- Exposed `"flows_flushed"` in `get_metrics()`.

### B. `streaming/inference_worker.py`
- Added `self._lock = threading.Lock()` for thread-safe state management.
- Re-architected `stop(self, drain_timeout: float = 5.0) -> None`:
  - Protects state transitions under `_lock` (idempotent, thread-safe).
  - Puts sentinel `None` at the end of the queue.
  - Waits for worker thread to process all queued items up to the sentinel.
  - Enforces hard timeout: if `join(timeout=drain_timeout)` expires, sets `_stop_event` to force halt.
  - Drains any remaining items in the queue and adds them to `self.unprocessed_flows`.
- Re-architected `_run_loop()`:
  - Consumes flows until sentinel `None` is encountered:
    ```python
    while not self._stop_event.is_set():
        try:
            flow = self.flow_queue.get(timeout=0.1)
            if flow is None:  # Sentinel reached
                self.flow_queue.task_done()
                break
            try:
                self._score_flow(flow)
            finally:
                self.flow_queue.task_done()
        except queue.Empty:
            if self._drain_requested.is_set() and self.flow_queue.empty():
                break
            continue
    ```
- Added `self.unprocessed_flows: int = 0` to operational telemetry and `get_metrics()`.

### C. `streaming/manager.py`
- Added `self.flows_queued: int = 0` counter tracking all flows fed into `self.flow_queue`.
- Re-ordered `stop(self, drain_timeout: float = 5.0)` to join `_pipeline_thread` *before* calling `flow_builder.flush()`, preventing packet ingestion races.
- Routed all flushed flows into `self.flow_queue` with timeout backpressure and queue accounting.
- Added graceful EOF drain for PCAP replay, transitioning naturally to `WorkerState.COMPLETED`.
- Exposed `flows_flushed`, `flows_queued`, `validation_errors`, and `unprocessed_flows` in `get_status()`.

### D. `ingestion/capture/base.py`
- Added `COMPLETED = "COMPLETED"` to `WorkerState` enum to support natural EOF termination without error.
