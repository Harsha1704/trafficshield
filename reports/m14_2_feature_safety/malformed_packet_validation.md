# TrafficShield M14.2 — Malformed & Truncated Packet Validation Gate

**Milestone:** M14.2 — Feature Fidelity and Malformed-Packet Safety Gate  
**Date:** 2026-10-23  
**Auditor:** Antigravity  
**Repository:** `D:\projects\trafficshield`  
**Verdict:** **VERIFIED & HARDENED**  

---

## 1. Executive Summary

A severe vulnerability in network anomaly detection systems is the corruption of flow features caused by malformed or truncated packet headers. Prior to Milestone 14.2, raw packets were passed into Scapy layers without pre-validation, allowing packets with impossible lengths or missing TTLs to generate phantom flow records.

TrafficShield now deploys an in-memory structural validator, [`IPv4PacketValidator`](file:///D:/projects/trafficshield/ingestion/capture/packet_validator.py), at the ingress of both [`PcapReplaySource`](file:///D:/projects/trafficshield/ingestion/capture/pcap_source.py) and [`LiveCaptureSource`](file:///D:/projects/trafficshield/ingestion/capture/live_source.py). Malformed and truncated packets are rejected prior to envelope generation with zero application payload retention.

---

## 2. Validation Taxonomy & Rejection Rules

The validator classifies incoming frames into four mutually exclusive categories:

```
[Raw Ingress Frame Bytes]
            │
            ├─► 1. VALID (Headers complete and structurally coherent)
            │      └─► Creates PacketEnvelope -> Dispatched to FlowBuilder
            │
            ├─► 2. MALFORMED (Impossible or contradictory headers)
            │      └─► Dropped -> Increments `malformed_packets` counter
            │
            ├─► 3. TRUNCATED (Header or frame cut off by network capture)
            │      └─► Dropped -> Increments `truncated_packets` counter
            │
            └─► 4. UNSUPPORTED (IPv6 or non-IPv4 framing)
                   └─► Dropped -> Increments `unsupported_packets` counter
```

### 2.1 Rejection Standards & Checkpoints

| Checkpoint | Tested Condition | Rejection Category | Specific Diagnostic Reason Code |
| :--- | :--- | :---: | :--- |
| **Minimum IPv4 Length** | `len(raw_bytes) < 20` | `TRUNCATED` | `TRUNCATED_IPV4_HEADER` |
| **IP Version** | `version == 6` | `UNSUPPORTED`| `UNSUPPORTED_IPV6` |
| **IP Version** | `version != 4 and version != 6` | `MALFORMED` | `MALFORMED_IP_VERSION` |
| **Header Length (IHL)** | `ihl < 5` ($< 20$ bytes) | `MALFORMED` | `MALFORMED_IHL_LESS_THAN_MIN` |
| **Options Truncation** | `len(raw_bytes) < ihl * 4` | `TRUNCATED` | `TRUNCATED_IPV4_OPTIONS` |
| **Total Length Lower Bound** | `total_len < ihl * 4` | `MALFORMED` | `MALFORMED_TOTAL_LEN_LESS_THAN_HEADER` |
| **Total Length Upper Bound** | `total_len > 65535` | `MALFORMED` | `MALFORMED_TOTAL_LEN_EXCEEDS_MAX` |
| **Time-to-Live (TTL)** | `ttl == 0` | `MALFORMED` | `MALFORMED_ZERO_TTL` |
| **TCP Minimum Length** | `total_len < ihl * 4 + 20` | `MALFORMED` | `MALFORMED_TCP_LENGTH` |
| **TCP Header Truncation** | `len(raw_bytes) < ihl * 4 + 20` | `TRUNCATED` | `TRUNCATED_TCP_HEADER` |
| **TCP Data Offset** | `tcp_data_offset < 20` | `MALFORMED` | `MALFORMED_TCP_OFFSET` |
| **UDP Minimum Length** | `total_len < ihl * 4 + 8` | `MALFORMED` | `MALFORMED_UDP_LENGTH` |
| **UDP Header Truncation** | `len(raw_bytes) < ihl * 4 + 8` | `TRUNCATED` | `TRUNCATED_UDP_HEADER` |
| **UDP Declared Length** | `udp_len < 8` or `udp_len > payload` | `MALFORMED` | `MALFORMED_UDP_LENGTH_FIELD` |

---

## 3. Disentangling Snaplen Truncation from Header Truncation

A crucial distinction exists between **snaplen truncation** and **header truncation**:
- **Header Truncation:** Captured bytes are fewer than the minimum IP/transport header size (`cap_len < header_len + transport_header_len`). In this case, ports and TTL cannot be verified. The packet is **REJECTED** as `TRUNCATED_IPV4_HEADER` or `TRUNCATED_TCP_HEADER`.
- **Snaplen Truncation:** Headers are completely captured (`cap_len >= header_len + transport_header_len`), but payload was cut short by packet capture tools (e.g., `tcpdump -s 68`). Because TrafficShield operates a **zero payload retention policy**, application payload is never examined. The on-wire byte count is extracted from the verified `ip.len` field (`total_len`). The frame is accepted for flow extraction, and `snaplen_truncated_packets` is incremented for analyst visibility.

---

## 4. Rejection Telemetry & Privacy Guarantees

- **Zero Payload Retention:** The validator operates strictly on header byte offsets. No payload content is logged, serialized, or retained in database tables.
- **Diagnostic Metrics:** Rejection counts are tracked in thread-safe memory and exposed via `GET /api/v1/capture/status`:
  ```json
  {
    "malformed_packets_rejected": 0,
    "truncated_packets_rejected": 0,
    "unsupported_packets_rejected": 0,
    "rejection_reasons": {}
  }
  ```

---

## 5. Verification Test Suite

All 9 validation test cases were verified in [`tests/unit/test_m14_2_feature_safety.py`](file:///D:/projects/trafficshield/tests/unit/test_m14_2_feature_safety.py#L26-L95):
- `test_valid_unfragmented_tcp_packet` [PASS]
- `test_truncated_header_less_than_20_bytes` [PASS]
- `test_invalid_ip_version` [PASS]
- `test_unsupported_ipv6_version` [PASS]
- `test_malformed_ihl_less_than_5` [PASS]
- `test_malformed_total_len_less_than_header` [PASS]
- `test_truncated_capture_snaplen` [PASS]
- `test_truncated_tcp_header_rejected` [PASS]
- `test_malformed_zero_ttl` [PASS]
- `test_malformed_tcp_offset_less_than_20` [PASS]
