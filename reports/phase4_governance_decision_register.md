# TrafficShield Phase 4 — Governance Decision Register
## Formal Policy Decisions Submitted to the Release Governance Board

**Document ID:** `REG-P4-DECISIONS-20261105`  
**Execution Date:** November 5, 2026  
**Governing Milestone:** Phase 4 — Controlled Release Preparation  
**Authority Matrix Reference:** [`phase4_signoff_authority_matrix.md`](file:///d:/projects/trafficshield/docs/phase4_signoff_authority_matrix.md)  
**Governance Scope:** Decisions D-P4-01, D-P4-02, and D-P4-03  

---

## 1. Master Decision Register Summary Table

| Decision ID | Subject & Scope | Proposed Outcome | Actual Board Decision | Approving Authority | Action Date | Status |
|---|---|---|---|---|---|---|
| **D-P4-01** | Warmup Acceptance Protocol Ratification | APPROVE 5-iteration warmup for steady-state SLA | *PENDING BOARD ACTION* | Lead ML Engineer & QA Lead | `[YYYY-MM-DD]` | **OPEN** |
| **D-P4-02** | Mandatory Operational Service Prewarming | APPROVE post-startup dummy inference gate | *PENDING BOARD ACTION* | DevSecOps Lead & Release Manager | `[YYYY-MM-DD]` | **OPEN** |
| **D-P4-03** | Final Phase 4 Release Gate Classification | PASS WITH LIMITATIONS (Technical Qualification) | *PENDING BOARD ACTION* | Release Governance Board (Unanimous) | `[YYYY-MM-DD]` | **OPEN** |

---

## 2. Decision D-P4-01: Warmup Acceptance Protocol Ratification

### 2.1 Decision Background
The Phase 4 acceptance test `test_single_flow_latency_benchmark` in `tests/integration/test_m14_end_to_end_release.py` enforces `assert mean_lat < 35.0`. The test currently executes 50 HTTP requests without warmup. Because `ProductionInferenceService` loads lazily on request 0, the first request absorbs ~2.15 seconds of artifact hashing, joblib deserialization, and 100-tree compilation. Averaged over 50 runs, the cold start adds $43.12\text{ ms}$ overhead, producing an average of ~60 ms and causing the test to fail. Conversely, steady-state warm inference is empirically proven to operate at **15.60 ms** (mean) and **24.22 ms** (P95), well below the 35.0 ms SLA.

### 2.2 Evidence Reviewed
1. [`phase4_wp2_benchmark_raw_results.csv`](file:///d:/projects/trafficshield/reports/phase4_wp2_benchmark_raw_results.csv): 4,750 warm measurements confirming 15.60 ms service mean and 15.07 ms warm HTTP loop mean.
2. [`phase4_cold_start_benchmark_reconciliation.md`](file:///d:/projects/trafficshield/reports/phase4_cold_start_benchmark_reconciliation.md): Detailed decomposition isolating the 2,155.98 ms cold deserialization overhead.
3. Test failure logs in task-12538: `AssertionError: Mean latency too high: 61.91ms`.

### 2.3 Alternatives Considered
- **Alternative 1 (Status Quo / No Warmup):** Maintain un-warmed 50-run test. Requires re-architecting detectors, pre-compiling decision trees into C/Cython, or replacing Isolation Forest.
- **Alternative 2 (Proposed 5-Run Warmup):** Execute 5 untimed warmup requests before timing 50 steady-state requests. Captures true operational request throughput while measuring cold start separately.
- **Alternative 3 (Increase SLA Threshold to 120 ms):** Loosen SLA to accommodate cold start in 50 runs. Rejected by ML Lead as masking true operational latency requirements.

### 2.4 Risks & Mitigations
- *Risk:* Conflating warm performance with cold-start readiness.
- *Mitigation:* Cold-start initialization time must be recorded and logged separately as an operational telemetry metric.

### 2.5 Board Voting Options
- [ ] **APPROVE:** Authorize amending `test_single_flow_latency_benchmark` to include a 5-iteration untimed warmup loop.
- [ ] **REJECT:** Maintain un-warmed test requirement; mandate engineering refactor.
- [ ] **REQUEST ADDITIONAL EVIDENCE:** Order further profiling.
- [ ] **DEFER:** Postpone decision.

### 2.6 Decision Execution Record (Blank Template)
```
Decision D-P4-01 Outcome:   [ PENDING BOARD ACTION ]
Authorized Vote:           [ APPROVE / REJECT / REQUEST EVIDENCE / DEFER ]
Approver Name (Lead ML):   [ ____________________________________________ ]
Approver Name (QA Lead):   [ ____________________________________________ ]
Execution Date:            [ YYYY-MM-DD ]
Board Notes / Conditions:  [ ____________________________________________ ]
```

---

## 3. Decision D-P4-02: Mandatory Operational Service Prewarming

### 3.1 Decision Background
If a production worker process begins routing live network traffic immediately after startup without prewarming, the first client request will experience a ~2.15-second latency spike while models deserialize, risking timeout violations in upstream load balancers or proxy gateways.

### 3.2 Evidence Reviewed
1. [`trafficshield_operational_runbook.md`](file:///d:/projects/trafficshield/docs/trafficshield_operational_runbook.md) §5: Operational prewarming workflow.
2. `ml/production_service.py` & `app/api/v1/predict.py`: Verification that lazy loading occurs on first call to `get_inference_service()`.

### 3.3 Proposed Operational Policy
Deployment scripts and systemd orchestrators must execute post-startup dummy inference calls (`/api/v1/predict`) to warm worker memory and verify model readiness before traffic cutover.

### 3.4 Operational Safeguards
1. Warmup calls must use synthetic validation vectors, not live traffic.
2. Dummy requests must not generate alert records in `alerts` or write false drift events.
3. Prewarming script must verify HTTP 200 before cutover; failure must abort deployment.

### 3.5 Board Voting Options
- [ ] **APPROVE:** Mandate operational prewarming as a required production cutover gate.
- [ ] **REJECT:** Allow live traffic to initialize the service lazily.
- [ ] **REQUEST ADDITIONAL EVIDENCE:** Require staging deployment prewarming logs.
- [ ] **DEFER:** Postpone operational mandate to Phase 7.

### 3.6 Decision Execution Record (Blank Template)
```
Decision D-P4-02 Outcome:   [ PENDING BOARD ACTION ]
Authorized Vote:           [ APPROVE / REJECT / REQUEST EVIDENCE / DEFER ]
Approver Name (DevSecOps): [ ____________________________________________ ]
Approver Name (Release):   [ ____________________________________________ ]
Execution Date:            [ YYYY-MM-DD ]
Board Notes / Conditions:  [ ____________________________________________ ]
```

---

## 4. Decision D-P4-03: Final Phase 4 Release Gate Classification

### 4.1 Decision Background
Phase 4 remediation has completed all five work packages, verified all 725 test cases, locked all 5 model artifacts, published the operational runbook, and reconciled all performance figures. The board must formally determine the final milestone classification.

### 4.2 Evidence Reviewed
1. [`phase4_release_governance_board_package.md`](file:///d:/projects/trafficshield/reports/phase4_release_governance_board_package.md).
2. [`phase4_final_closure_report.md`](file:///d:/projects/trafficshield/reports/phase4_final_closure_report.md).
3. [`phase4_release_acceptance_matrix.md`](file:///d:/projects/trafficshield/reports/phase4_release_acceptance_matrix.md).

### 4.3 Board Voting Options
- [ ] **PASS (CLOSED):** Authorize full closure of Phase 4 (requires unanimous approval of D-P4-01, D-P4-02, and all 5 stakeholder sign-offs).
- [ ] **PASS WITH LIMITATIONS:** Ratify technical qualification; record residual limitations (cold-start spike, SQLite/PostgreSQL parity); authorize convening Phase 5 review. *(Recommended)*
- [ ] **FAIL / REJECT:** Declare Phase 4 incomplete; return to remediation.

### 4.4 Decision Execution Record (Blank Template)
```
Decision D-P4-03 Outcome:   [ PENDING BOARD ACTION ]
Authorized Vote:           [ PASS / PASS WITH LIMITATIONS / FAIL ]
Release Manager:           [ ____________________________________________ ]
Principal Architect:       [ ____________________________________________ ]
DevSecOps Lead:            [ ____________________________________________ ]
Lead ML Engineer:          [ ____________________________________________ ]
Independent QA Auditor:    [ ____________________________________________ ]
Execution Date:            [ YYYY-MM-DD ]
Board Notes / Conditions:  [ ____________________________________________ ]
```

---
*End of Governance Decision Register REG-P4-DECISIONS-20261105*
