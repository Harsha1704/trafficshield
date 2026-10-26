# TrafficShield M14.2.1 — Feature Mapping Discrepancy & Root Cause Analysis

**Document ID:** TS-M14-2-1-DIFF  
**Date:** 2026-10-24  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Scope:** Root-cause investigation and line-by-line reconciliation of the feature table published in `reports/m14_2_feature_safety/` against the authoritative model contract.

---

## 1. Discrepancy Overview

In `reports/m14_2_feature_safety/final_gate_verdict.md`, Section 2 published a table entitled *"Revised 13-Feature Semantic Audit Matrix"* listing:
`dur`, `proto`, `state`, `spkts`, `sbytes`, `sttl`, `sload`, `sjit`, `smeansz`, `trans_depth`, `res_bdy_len`, `ct_state_ttl`, `ct_flw_http_mthd`.

However, the authoritative frozen artifacts (`production_preprocessor.joblib` and `production_detector.joblib`), `ProductionInferenceService`, `UnidirectionalFlowBuilder`, and the original training pipeline in `ml/tournament.py` use:
`duration_seconds`, `fwd_bytes`, `sttl`, `sload`, `fwd_packets`, `swin`, `smeansz`, `sjit`, `sintpkt`, `is_sm_ips_ports`, `packet_rate`, `byte_rate`, `bytes_per_packet`.

---

## 2. Root Cause Analysis: Documentation Erratum vs Code Pipeline

An exhaustive audit of the codebase, model artifacts, and test execution history establishes that:

1. **The discrepancy is 100% a documentation-only erratum.**
2. **The runtime code was never contaminated.**
   - [`ingestion/flow/flow_builder.py`](file:///d:/projects/trafficshield/ingestion/flow/flow_builder.py) has always constructed the 10 base features + 3 derived rates.
   - [`ml/production_service.py`](file:///d:/projects/trafficshield/ml/production_service.py) enforces `REQUIRED_BASE_FEATURES = ["duration_seconds", "fwd_bytes", "sttl", "sload", "fwd_packets", "swin", "smeansz", "sjit", "sintpkt", "is_sm_ips_ports"]`.
   - [`streaming/inference_worker.py`](file:///d:/projects/trafficshield/streaming/inference_worker.py) persists these exact 10 base features into `SecurityAlert.input_features`.
   - `artifacts/models/production_preprocessor.joblib` requires these exact 13 features.
   - `artifacts/models/production_detector.joblib` predicts on these exact 13 features.
3. **Provenance of the Erroneous Table:**
   During the authoring of `final_gate_verdict.md` in M14.2, an informal table of raw UNSW-NB15 dataset columns (derived from early exploratory feature audits in `reports/m14_release/preflight_findings.md` and raw UNSW-NB15 schemas) was mistakenly adapted into the M14.2 report table. 

---

## 3. Policy & Unidirectional Observability Audit of Discrepant Fields

The erroneous table included several fields that directly violate TrafficShield's core architectural tenets:

| Erroneous Report Feature | Policy Role in `features/policy.py` | Architectural Rationale & Why It Cannot Be in Model |
| :--- | :--- | :--- |
| `res_bdy_len` | **`FORBIDDEN`** | Server HTTP response body length. In unidirectional monitoring links, the reverse path (server to client) is unobservable. Feeding `res_bdy_len` violates zero-directional-leakage. |
| `trans_depth` | **`FORBIDDEN`** | Pipelined HTTP request/response transaction depth. Requires observing request-response pairs across both directions. |
| `ct_state_ttl` | **`FORBIDDEN`** | Connection state count by TTL range. Depends on bidirectional state tracking across return flows. |
| `proto` | *Metadata Only* | Categorical protocol string (`TCP`, `UDP`, `ICMP`). Stored in flow metadata and database alert records; not encoded as a numeric feature in the frozen model. |
| `state` | *Metadata Only* | Connection state string (`CON`, `INT`, `FIN`). Not included in the frozen model's numerical input contract. |
| `ct_flw_http_mthd` | *Eligible but Excluded* | Forward HTTP method count. Eligible under policy, but excluded during M8/M9 tournament when `strict_causal_only=True` was established to eliminate multi-flow lookahead. |

If `res_bdy_len`, `trans_depth`, or `ct_state_ttl` had ever been submitted to `ProductionInferenceService.validate_and_prepare_input()`, the service would have immediately raised a fatal `PolicyViolationError`:
> *"Forbidden reverse-dependent columns rejected: ['res_bdy_len']"*

---

## 4. Side-by-Side Comparative Diff

| Authoritative Model Contract (Code & Model) | Erroneous M14.2 Report Table (`final_gate_verdict.md`) | Discrepancy Classification | Status in Production System |
| :--- | :--- | :--- | :--- |
| `duration_seconds` | `dur` | Naming discrepancy (Canonical normalized name vs raw UNSW-NB15 name) | **ACTIVE & VERIFIED** |
| `fwd_bytes` | `sbytes` | Naming discrepancy (Canonical normalized name vs raw UNSW-NB15 name) | **ACTIVE & VERIFIED** |
| `sttl` | `sttl` | Match | **ACTIVE & VERIFIED** |
| `sload` | `sload` | Match | **ACTIVE & VERIFIED** |
| `fwd_packets` | `spkts` | Naming discrepancy (Canonical normalized name vs raw UNSW-NB15 name) | **ACTIVE & VERIFIED** |
| `swin` | *(Omitted in error)* | Documentation omission | **ACTIVE & VERIFIED** |
| `smeansz` | `smeansz` | Match | **ACTIVE & VERIFIED** |
| `sjit` | `sjit` | Match | **ACTIVE & VERIFIED** |
| `sintpkt` | *(Omitted in error)* | Documentation omission | **ACTIVE & VERIFIED** |
| `is_sm_ips_ports` | *(Omitted in error)* | Documentation omission | **ACTIVE & VERIFIED** |
| `packet_rate` | *(Omitted in error)* | Documentation omission | **ACTIVE & VERIFIED** |
| `byte_rate` | *(Omitted in error)* | Documentation omission | **ACTIVE & VERIFIED** |
| `bytes_per_packet` | *(Omitted in error)* | Documentation omission | **ACTIVE & VERIFIED** |
| *(Metadata Only)* | `proto` | Erroneous inclusion of string metadata as model feature | **METADATA ONLY** |
| *(Metadata Only)* | `state` | Erroneous inclusion of string metadata as model feature | **METADATA ONLY** |
| *(Forbidden)* | `trans_depth` | Erroneous inclusion of forbidden bidirectional field | **STRICTLY FORBIDDEN** |
| *(Forbidden)* | `res_bdy_len` | Erroneous inclusion of forbidden reverse-direction field | **STRICTLY FORBIDDEN** |
| *(Forbidden)* | `ct_state_ttl` | Erroneous inclusion of forbidden bidirectional field | **STRICTLY FORBIDDEN** |
| *(Excluded)* | `ct_flw_http_mthd` | Erroneous inclusion of non-causal multi-flow counter | **EXCLUDED FROM CONTRACT** |

---

## 5. Conclusion

The production model contract is, and has always been, the **10 base causal forward features + 3 derived causal rates**. The erroneous entries in `reports/m14_2_feature_safety/final_gate_verdict.md` are formally superseded by this report and [`authoritative_model_contract.md`](./authoritative_model_contract.md).
