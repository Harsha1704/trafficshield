# TrafficShield M15.3 — Flow Accounting & Conservation Audit

**Document ID:** TS-M15.3-ACCOUNTING  
**Date:** 2026-10-26  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Scope:** Mathematical proof of flow conservation and counter reconciliation from the post-fix live Wi-Fi smoke test.

---

## 1. Mathematical Proof of Flow Conservation

The M15.3 post-fix live smoke test demonstrates exact mathematical reconciliation across all flow lifecycle stages:

```
[ 11,506 Wire Packets ]
          │
          ▼
 [ 884 Flows Created ] ═══════════════════════════════════════╗
          │                                                    ║
          ├──► 833 Flows Completed via Idle Timeout / TCP FIN  ║ Invariant:
          │                                                    ║ flows_created =
          └──►  51 Flows Flushed at Session Shutdown           ║ flows_completed
                  │                                            ║ 884 = 833 + 51
                  ▼                                            ║
         [ 884 Flows Completed ] ══════════════════════════════╣
                  │                                            ║
                  ▼ (0 Queue Drops)                            ║ Invariant:
          [ 884 Flows Queued ] ════════════════════════════════╣ flows_completed =
                  │                                            ║ flows_queued
                  ▼                                            ║ 884 = 884
          [ 884 Flows Scored ] ════════════════════════════════╝
                  │  • Incompatible: 0
                  │  • Validation Errors: 0
                  │  • Inference Failures: 0
                  │  • Unprocessed: 0
                  │
                  ├──► 418 Flows Scored Benign (P < 0.50)
                  │
                  └──► 466 Flows Scored Anomalous (P >= 0.50)
                            │
                            ├──► 177 Deduplicated within 10s Window
                            │
                            └──► 289 Unique Alerts Persisted to SQLite
```

---

## 2. Invariant Reconciliation Check

### Invariant 1: Ingestion & Completion Balance
$$\text{flows\_created} = \text{active\_flows\_count} + \text{flows\_completed}$$
At capture start: $0 = 0 + 0 \quad \checkmark$  
At capture midpoint: $884 = 51 + 833 \quad \checkmark$  
After orderly shutdown: $884 = 0 + 884 \quad \checkmark$

### Invariant 2: Flow Completion Breakdown
$$\text{flows\_completed} = \text{flows\_closed\_live} + \text{flows\_flushed}$$
$$\text{flows\_completed} = 833 + 51 = \mathbf{884} \quad \checkmark$$

### Invariant 3: Queue & Inference Terminal Balance
$$\text{flows\_queued} = \text{flows\_scored} + \text{incompatible\_flows\_rejected} + \text{validation\_errors} + \text{inference\_failures} + \text{unprocessed\_flows}$$
$$\text{flows\_queued} = 884 + 0 + 0 + 0 + 0 = \mathbf{884} \quad \checkmark$$

### Invariant 4: Alert Deduplication Conservation
$$\text{anomalies\_detected} = \text{alerts\_persisted} + \text{alerts\_suppressed\_dedup}$$
$$\text{anomalies\_detected} = 289 + 177 = \mathbf{466} \quad \checkmark$$

---

## 3. Discrepancy Resolution: M15.1 vs M15.3

| Milestone | Capture Window | Flows Created | Flows Completed | Flows Scored | Unscored Gap | Unprocessed Flows | Root Cause |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---|
| **M15.1** | 24.1s | 757 | 757 | 668 | **89** | 89 | Worker loop exited on stop signal before draining queue. |
| **M15.3** | 35.0s | 884 | 884 | 884 | **0** | **0** | **Resolved.** Sentinel-based graceful drain scores all flushed flows. |

**Conclusion:** The unscored-flow gap has been completely, verifiably eliminated. No flows were silently discarded, reclassified, or lost.
