# TrafficShield — One-Way Feature Eligibility Policy

Version: 1.0  
Date: 2026-10-22  
Milestone: M2

## Premise

TrafficShield is designed for critical-infrastructure monitoring links that observe traffic in **one direction only**. The detection pipeline must not depend on:

- Reverse-direction traffic (replies, acknowledgements, return packets)
- Response timing (RTT, request-response latency)
- Bidirectional session state (TCP handshake completion across both directions)
- Any information that requires observing the opposite link direction

## Eligibility Categories

### ✅ ELIGIBLE — Can be computed from single-direction observation

These fields are allowed as model inputs:

| Feature | Source | Rationale |
|---------|--------|-----------|
| Flow end timestamp (`te`) | UGR'16 | Observed at collection point |
| Flow duration (`td`) | UGR'16 | Derived from observed packet timestamps |
| Source IP (`sa`) | UGR'16 | Observed in packet headers |
| Destination IP (`da`) | UGR'16 | Observed in packet headers |
| Source port (`sp`) | UGR'16 | Observed in packet headers |
| Destination port (`dp`) | UGR'16 | Observed in packet headers |
| Protocol (`pr`) | UGR'16 | Observed in packet headers |
| TCP flags as seen (`flg`) | UGR'16 | Flags from observed direction only |
| Type of Service (`stos`) | UGR'16 | Observed in IP header |
| Packet count (`pkt`) | UGR'16 | Counted in observed direction |
| Byte count (`byt`) | UGR'16 | Counted in observed direction |
| Packets per second | Derived | pkt / td (when td > 0) |
| Bytes per second | Derived | byt / td (when td > 0) |
| Bytes per packet (mean) | Derived | byt / pkt |
| Destination port is well-known | Derived | dp < 1024 |
| Protocol is TCP/UDP/ICMP | Derived | from pr field |
| Hour of day / day of week | Derived | from te timestamp |
| Destination IP fan-out (per source, window) | Derived | count distinct da per sa |
| Destination port fan-out (per source, window) | Derived | count distinct dp per sa |

### ❌ PROHIBITED — Require reverse-direction data

These fields must NEVER be used as model inputs:

| Feature | Reason |
|---------|--------|
| Backward packet count | Requires observing return direction |
| Backward byte count | Requires observing return direction |
| Forward/backward ratio (any) | Requires both directions |
| TCP response time / RTT | Requires SYN-ACK from reverse direction |
| Session completion flag (bidirectional) | Requires observing FIN/RST from both sides |
| Bidirectional flow duration (true) | May depend on last reverse-direction packet |
| Response packet size | Requires reverse direction |
| Inter-arrival time derived from responses | Requires reverse direction |
| CICIDS2017 "Bwd Packet Length*" fields | Explicitly reverse-direction |
| CICIDS2017 "Bwd Header Length" | Explicitly reverse-direction |
| CICIDS2017 "Flow Bytes/s" (bidirectional) | Ambiguous — excluded unless verified unidirectional |

### ⚠️ CONDITIONAL — Require per-dataset verification

| Feature | Condition |
|---------|-----------|
| Flow duration (`td`) | Eligible IF duration is measured from first observed packet to last observed packet in the monitored direction. Prohibited if it represents round-trip session duration. For UGR'16 specifically, `td` is the NetFlow flow duration measured at the export point — treated as eligible. |
| TCP flags (`flg`) | Eligible for flags observed in this direction. In UGR'16, flags are cumulative across packets in the flow; they may include ACKs that could theoretically indicate receipt of reverse data. Treated as conditionally eligible with the caveat documented here. |
| Forwarding status (`fwd`) | Router-level field; does not require reverse observation. Eligible. |

### ⛔ ALWAYS EXCLUDED — Labels and post-event information

| Field | Reason |
|-------|--------|
| `class` (UGR'16) | Attack label — used only for post-prediction evaluation |
| `Label` (CICIDS2017) | Attack label |
| `attack_cat` (UNSW-NB15) | Attack category |
| Any field encoding attack identity | Data leakage into training |

## Implementation Contract

The feature eligibility policy is enforced programmatically:

1. `ingestion/schema/canonical_flow.py` — defines `ELIGIBLE_FEATURE_COLUMNS` and `PROHIBITED_COLUMNS`
2. `preprocessing/` (M3) — validates that no prohibited column enters the feature matrix
3. `tests/unit/test_feature_eligibility.py` — tests that prohibition rules cannot be bypassed

## Dataset-Specific Notes

### UGR'16
- The `class` column is retained in `CanonicalFlow.eval_label` (Optional, not in feature set)
- The `fwd` (forwarding status) field is router-internal metadata; it is eligible but may be uninformative for anomaly detection
- IPs are anonymized with CryptoPan — they cannot be reverse-mapped but retain topological structure, making per-IP behavioural features valid

### CICIDS2017
- CICFlowMeter produces explicit bidirectional features. The adapter (M11) will apply this eligibility filter to retain only forward-direction columns.
- Columns with "Bwd" in their name are prohibited without individual review.

## Version History

| Version | Date | Change |
|---------|------|--------|
| 1.0 | 2026-10-22 | Initial policy, UGR'16 and CICIDS2017 coverage |
