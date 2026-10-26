# TrafficShield M18 — Memory Policy Audit & Accounting Reconciliation

**Document ID:** TS-M18-MEM-AUDIT  
**Date:** 2026-10-26  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Milestone:** M18 Memory Policy Review & Native Npcap Statistics  
**Baseline Commit:** `025ebaa`  
**Gate Verdict:** **`READY FOR LOCAL DEMONSTRATION`** (Maintained)  

---

## 1. Executive Summary & Policy Analysis

Milestone 18 audited the memory acceptance policy implemented in `tools/soak/memory_policy.py` (`MemoryStabilityPolicy`) and evaluated its behavioral guarantees across boundary conditions, cold-start initialization, and steady-state soak testing.

The audit verified:
1. What each rule mode (`OR`, `AND`, `ABSOLUTE_ONLY`, `RELATIVE_ONLY`) mathematically guarantees and does not guarantee.
2. The operational distinction between cold-start module importation and post-warmup steady-state telemetry.
3. The exact reconciliation of all 5 stages of flow and alert accounting invariants.

---

## 2. Policy Mode Guarantees & Non-Guarantees

The `MemoryStabilityPolicy` evaluates resident set size (RSS) drift using three primary thresholds:
- $\text{max\_absolute\_growth\_mb} = 250.0\text{ MB}$
- $\text{max\_relative\_growth\_pct} = 50.0\%$
- $\text{min\_absolute\_headroom\_mb} = 50.0\text{ MB}$

### 2.1 Mode Comparison Matrix

| Policy Mode | Operational Guarantee | Non-Guarantee (Edge Case Risk) | Recommended Operating Context |
| :--- | :--- | :--- | :--- |
| **`OR`** (Default M17/M17.1) | Guarantees drift does not breach **both** absolute and relative limits simultaneously. Passes if $\Delta\text{RSS} \le 250\text{ MB}$ OR $\text{rel\_pct} \le 50\%$. | **Does NOT guarantee $\Delta\text{RSS} \le 250\text{ MB}$** on large baselines (e.g., 800 MB baseline growing 350 MB is only 43.7% relative, so it passes). **Does NOT guarantee $\text{rel} \le 50\%$** on moderate baselines (e.g., 100 MB baseline growing 200 MB is 200% relative, but passes because $200 \le 250\text{ MB}$). | Cold-start qualification or short smoke tests where initial module imports jump memory before steady state is established. |
| **`AND`** | **Strict Guarantee:** Absolute growth MUST be $\le 250\text{ MB}$ under all conditions, AND relative growth MUST be $\le 50\%$ (unless within the $50\text{ MB}$ headroom floor). | Rejects runs where cold-start module unpickling occurs post-baseline if the expansion exceeds both 50 MB headroom and 50% relative growth. | **Recommended for multi-hour steady-state soak testing** where baseline is established post-warmup. |
| **`ABSOLUTE_ONLY`** | Guarantees $\Delta\text{RSS} \le 250.0\text{ MB}$ strictly. Completely invariant to baseline magnitude. | Permits large relative spikes on small baselines (e.g., 20 MB growing to 260 MB is a 1200% increase, but passes). | High-memory worker processes with known, large steady-state footprints. |
| **`RELATIVE_ONLY`** | Guarantees proportional stability ($\le 50\%$ growth, protected by 50 MB headroom). | Permits unbounded absolute memory expansion on large enterprise servers (e.g. 2 GB baseline growing by 900 MB is 45%, but represents a huge 900 MB leak). | Homogeneous container environments with uniform, predictable baselines. |

---

## 3. Boundary & Edge Case Verification

The policy behavior was audited against specific test scenarios:
1. **Growth within both limits:** (e.g., Baseline 120 MB $\to$ Final 150 MB, $\Delta = 30\text{ MB}, 25.0\%$) $\to$ **PASS** across all modes.
2. **Growth within absolute limit but over relative limit:** (e.g., Baseline 100 MB $\to$ Final 180 MB, $\Delta = 80\text{ MB}, 80.0\%$) $\to$ **PASS** under `OR` and `ABSOLUTE_ONLY`; **FAIL** under `AND` and `RELATIVE_ONLY`.
3. **Growth over absolute limit but within relative limit:** (e.g., Baseline 600 MB $\to$ Final 860 MB, $\Delta = 260\text{ MB}, 43.3\%$) $\to$ **PASS** under `OR` and `RELATIVE_ONLY`; **FAIL** under `AND` and `ABSOLUTE_ONLY`.
4. **Growth over both limits:** (e.g., Baseline 200 MB $\to$ Final 500 MB, $\Delta = 300\text{ MB}, 150.0\%$) $\to$ **FAIL** across all modes.
5. **Low-Baseline Headroom Floor:** (e.g., Baseline 20 MB $\to$ Final 50 MB, $\Delta = 30\text{ MB}, 150.0\%$) $\to$ **PASS** under `AND` mode because $\Delta = 30\text{ MB} \le 50\text{ MB}$ headroom floor.
6. **Unavailable Measurements:** Either baseline or final RSS is `None` $\to$ **FAIL** with explicit error diagnostic, never substituting zero.
7. **Exact Threshold Boundaries:** $\Delta = 250.00\text{ MB}$ **PASS**; $\Delta = 250.01\text{ MB}$ **FAIL**.
8. **OS Page Reclamation / Decreased Memory:** $\Delta \le 0.0\text{ MB}$ $\to$ **PASS**.

---

## 4. Accounting Invariants Verification

All five stages of flow and alert accounting invariants from M17.1 were re-verified against actual code:

1. **Packet Conservation:**
   $$\text{packets\_total} = \text{packets\_valid} + \text{packets\_dropped} + (\text{malformed} + \text{truncated} + \text{unsupported})$$
2. **Flow Reconstruction:**
   $$\text{flows\_created} = \text{flows\_completed} + \text{active\_flows\_count}$$
   After teardown: $\text{active\_flows\_count} == 0 \implies \text{flows\_created} == \text{flows\_completed}$.
3. **Queue Ingestion:**
   $$\text{flows\_completed} = \text{flows\_queued} + \text{flows\_queue\_dropped}$$
4. **Terminal Scoring Partition (Mutually Exclusive):**
   $$\text{flows\_queued} = \text{flows\_scored} + \text{incompatible\_flows\_rejected} + \text{validation\_errors} + \text{inference\_failures} + \text{unprocessed\_flows}$$
5. **Alert Persistence Conservation (Mutually Exclusive):**
   $$\text{anomalies\_detected} = \text{alerts\_persisted} + \text{persistence\_failures} + \text{alerts\_deduplicated} + \text{alerts\_unpersisted\_no_app}$$

**Audit Conclusion:** The accounting invariant implementation is free of double-counting and omission defects.
