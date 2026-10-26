# TrafficShield M14.2 — Fragment Handling & Safe Exclusion Engine

**Milestone:** M14.2 — Feature Fidelity and Malformed-Packet Safety Gate  
**Date:** 2026-10-23  
**Auditor:** Antigravity  
**Repository:** `D:\projects\trafficshield`  
**Verdict:** **VERIFIED (BOUNDED REASSEMBLY & SAFE EXCLUSION)**  

---

## 1. Executive Summary

In Milestone 14.1, an inspection of adversarial packet handling revealed that non-initial IPv4 fragments (`frag_offset > 0`) lacked transport headers (TCP/UDP ports) and were erroneously assigned to a separate flow with protocol `"OTHER"` and port 0, then scored as standalone traffic.

To resolve this defect, Milestone 14.2 implements a stateful, bounded reassembler, [`BoundedFragmentReassembler`](file:///D:/projects/trafficshield/ingestion/flow/fragment_reassembler.py).
- **Legitimate Complete Fragments:** Reassembled in memory into full IPv4 datagrams with verified transport headers and total byte counts.
- **Incomplete / Expired / Orphan Fragments:** Safely discarded and **excluded from production model inference**.
- **No Phantom Flows:** Non-initial fragments are **never** scored as phantom port 0 flows.

---

## 2. Fragment Reassembly Architecture

```
[Ingress Fragmented IPv4 Packet]
              │
              ▼
    Is MF==1 or Offset > 0?
              │
      ┌───────┴───────┐
      ▼               ▼
    No (Single)     Yes (Fragmented)
      │               │
      │               ▼
      │    Key: (src_ip, dst_ip, ip_id, proto)
      │               │
      │    Check Capacity & Expiration (max 500 buffers, 3.0s timeout)
      │               │
      │    Insert slice [offset : offset + payload_len]
      │               │
      │    Are all contiguous bytes [0 : total_len] present?
      │               │
      │       ┌───────┴───────┐
      │       ▼               ▼
      │     No (In-Flight)   Yes (Complete)
      │       │               │
      │       ▼               ▼
      │    Wait in memory  Reconstruct full IPv4 datagram
      │    (Exclude from   (Clear MF/Offset, update Total Length)
      │     inference)        │
      │                       ▼
      └───────────────► Parse Transport Header (TCP/UDP ports)
                              │
                              ▼
                      Emit PacketEnvelope
                              │
                              ▼
                  UnidirectionalFlowBuilder
```

---

## 3. Defense Against Fragmentation Attacks & Resource Bounds

To prevent memory exhaustion and fragmentation-based denial-of-service attacks, the reassembler enforces three strict limits:

| Resource Constraint | Configured Bound | Failure Action | Telemetry Metric |
| :--- | :---: | :--- | :--- |
| **Max In-Flight Datagrams** | **500 buffers** | Evicts oldest in-flight datagram state via LRU policy. | `dropped_capacity` |
| **Reassembly Timeout** | **3.0 seconds** | Stale fragment buffers lacking subsequent slices are purged. | `dropped_timeout` |
| **Max Datagram Size** | **65,535 bytes** | Rejects oversized datagrams (e.g. Ping of Death). | `dropped_oversize` |
| **Orphan Non-Initial Slices** | N/A | Held until timeout; discarded without creating phantom flow. | `dropped_incomplete` |

### Zero Fabrication Guarantee
Under no circumstances does TrafficShield guess or fabricate transport layer ports for unreassembled fragments. If a datagram cannot be completely reassembled, its fragments are counted in `fragment_metrics` and dropped. They **never reach the production inference service**.

---

## 4. Verification Test Evidence

The reassembler was subjected to 6 rigorous unit tests covering all required adversarial conditions in [`tests/unit/test_m14_2_feature_safety.py`](file:///D:/projects/trafficshield/tests/unit/test_m14_2_feature_safety.py#L98-L185):

1. **`test_in_order_two_fragments_reassemble_cleanly` [PASS]:**
   Fragment 1 (MF=1, offset 0, 104B) + Fragment 2 (MF=0, offset 104, 76B) reassemble into a complete 200B datagram with transport header preserved.
2. **`test_out_of_order_fragments_reassemble_cleanly` [PASS]:**
   Fragment 2 arrives before Fragment 1. Slices are placed at correct offsets; reassembly succeeds upon Fragment 1 arrival.
3. **`test_duplicate_fragments_handled_gracefully` [PASS]:**
   Duplicate copies of Fragment 1 are ignored without buffer corruption or size double-counting.
4. **`test_fragment_timeout_and_expiration` [PASS]:**
   An orphaned initial fragment without Fragment 2 is purged after 0.05s timeout, incrementing `dropped_timeout`.
5. **`test_capacity_bound_lru_eviction` [PASS]:**
   Exceeding max capacity (3 in-flight) evicts the oldest buffer, incrementing `dropped_capacity`.
6. **`test_oversize_fragment_rejected` [PASS]:**
   A fragment slice attempting to write past `max_reassembled_bytes` is immediately rejected, incrementing `dropped_oversize`.

---

## 5. Audit Verdict

| Verification Item | Target Standard | Forensic Finding | Verdict |
| :--- | :--- | :--- | :---: |
| **Complete Fragment Reassembly** | In-order & out-of-order reassembly | Verified in test suite | **VERIFIED** |
| **Incomplete Fragment Exclusion** | Never score orphan fragments as port 0 | Dropped prior to envelope emission | **VERIFIED** |
| **Resource & DoS Protection** | Bounded capacity (500) and timeout (3s) | LRU eviction and timeout confirmed | **VERIFIED** |
| **Telemetry Accounting** | Metrics exposed via status API | `fragment_metrics` dictionary tracked | **VERIFIED** |
