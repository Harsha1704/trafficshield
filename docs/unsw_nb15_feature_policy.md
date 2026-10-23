# TrafficShield — UNSW-NB15 Unidirectional Feature Eligibility Policy

Version: 1.0  
Dataset: UNSW-NB15 Network Intrusion Dataset  
Premise: Unidirectional Link Monitoring (Zero Reverse / Bidirectional Leakage)

## Summary of Classification

| Category | Count | Status | Description |
|---|---|---|---|
| `forward_observable` (numeric) | 19 | ✅ Eligible | Observable exclusively in forward packet stream |
| `forward_observable` (metadata) | 4 | ℹ️ Encoded | Ports/Protocol headers (categorical encoding only) |
| `reverse_direction` | 13 | ❌ Prohibited | Requires unobserved return traffic |
| `bidirectional_or_future_dependent` | 6 | ❌ Prohibited | Handshake state, RTT, or response pairing |
| `identifier_or_grouping_only` | 7 | ⛔ Excluded | IPs, timestamps, and ground-truth evaluation labels |

---

## Detailed Column-by-Column Policy

| # | Raw Name | Normalized | Category | Role | Model Feature? | Rationale |
|---|---|---|---|---|---|---|
| 1 | `srcip` | `src_ip` | `identifier_or_grouping_only` | `identifier` | ❌ NO | Network entity identifier. Used for entity tracking / state grouping; never a continuous numeric feature. |
| 2 | `sport` | `src_port` | `forward_observable` | `metadata` | ❌ NO | Observed directly in forward transport header. Encoded into well-known / ephemeral categories, not raw scalar magnitude. |
| 3 | `dstip` | `dst_ip` | `identifier_or_grouping_only` | `identifier` | ❌ NO | Network entity identifier. Prohibited from numeric feature matrix. |
| 4 | `dsport` | `dst_port` | `forward_observable` | `metadata` | ❌ NO | Observed directly in forward transport header. Encoded into service port categories / well-known indicators. |
| 5 | `proto` | `protocol_name` | `forward_observable` | `metadata` | ❌ NO | Observed in forward IP header protocol field. Categorical indicator. |
| 6 | `state` | `state` | `bidirectional_or_future_dependent` | `forbidden` | ❌ NO | ARGUS derives connection states (FIN, CON, CLO) by observing bidirectional TCP handshakes and teardowns across both link directions. |
| 7 | `dur` | `duration_seconds` | `forward_observable` | `feature` | ✅ YES | Elapsed time from first observed forward packet to last observed forward packet at the monitoring link. |
| 8 | `sbytes` | `fwd_bytes` | `forward_observable` | `feature` | ✅ YES | Cumulative forward byte volume observable from packet length headers. |
| 9 | `dbytes` | `bwd_bytes` | `reverse_direction` | `forbidden` | ❌ NO | Reverse-direction byte count. Requires observing return traffic. Strictly prohibited. |
| 10 | `sttl` | `sttl` | `forward_observable` | `feature` | ✅ YES | Observed directly in forward IP header TTL field. |
| 11 | `dttl` | `dttl` | `reverse_direction` | `forbidden` | ❌ NO | Reverse IP header TTL. Requires observing return packets. Strictly prohibited. |
| 12 | `sloss` | `sloss` | `bidirectional_or_future_dependent` | `forbidden` | ❌ NO | In ARGUS flow monitors, drop estimation often relies on reverse SACK or response acknowledgment gaps. Excluded fail-safe. |
| 13 | `dloss` | `dloss` | `reverse_direction` | `forbidden` | ❌ NO | Reverse-direction packet loss. Requires observing return traffic. Strictly prohibited. |
| 14 | `service` | `service` | `forward_observable` | `metadata` | ❌ NO | Derived from destination port and forward packet payload signature. |
| 15 | `Sload` | `sload` | `forward_observable` | `feature` | ✅ YES | Forward transmission rate (8 * sbytes / dur). Fully observable from forward stream. |
| 16 | `Dload` | `dload` | `reverse_direction` | `forbidden` | ❌ NO | Reverse-direction transmission rate. Requires return bytes. Strictly prohibited. |
| 17 | `Spkts` | `fwd_packets` | `forward_observable` | `feature` | ✅ YES | Cumulative forward packet count observable at sensor interface. |
| 18 | `Dpkts` | `bwd_packets` | `reverse_direction` | `forbidden` | ❌ NO | Reverse packet count. Requires observing return traffic. Strictly prohibited. |
| 19 | `swin` | `swin` | `forward_observable` | `feature` | ✅ YES | Observed in forward TCP header window field. |
| 20 | `dwin` | `dwin` | `reverse_direction` | `forbidden` | ❌ NO | Observed in reverse TCP header window field. Strictly prohibited. |
| 21 | `stcpb` | `stcpb` | `identifier_or_grouping_only` | `identifier` | ❌ NO | Random 32-bit transaction identifier without physical continuous magnitude. |
| 22 | `dtcpb` | `dtcpb` | `reverse_direction` | `forbidden` | ❌ NO | Destination sequence number from reverse TCP header. Strictly prohibited. |
| 23 | `smeansz` | `smeansz` | `forward_observable` | `feature` | ✅ YES | Mean forward packet size (sbytes / Spkts). Observable in forward direction. |
| 24 | `dmeansz` | `dmeansz` | `reverse_direction` | `forbidden` | ❌ NO | Mean reverse packet size. Requires return packets. Strictly prohibited. |
| 25 | `trans_depth` | `trans_depth` | `bidirectional_or_future_dependent` | `forbidden` | ❌ NO | Requires tracking request-response pairs across both link directions. |
| 26 | `res_bdy_len` | `res_bdy_len` | `reverse_direction` | `forbidden` | ❌ NO | Server response body transferred from destination back to source. Strictly prohibited. |
| 27 | `Sjit` | `sjit` | `forward_observable` | `feature` | ✅ YES | Variation in inter-packet arrival times of forward packets. |
| 28 | `Djit` | `djit` | `reverse_direction` | `forbidden` | ❌ NO | Variation in inter-packet arrival times of return packets. Strictly prohibited. |
| 29 | `Stime` | `flow_start_ts` | `identifier_or_grouping_only` | `timestamp` | ❌ NO | Timestamp used for ordering and windowing; excluded from numeric feature matrix. |
| 30 | `Ltime` | `flow_end_ts` | `identifier_or_grouping_only` | `timestamp` | ❌ NO | Primary chronological ordering key for flow completion. Excluded from numeric features. |
| 31 | `Sintpkt` | `sintpkt` | `forward_observable` | `feature` | ✅ YES | Time elapsed between consecutive forward packets. Fully forward observable. |
| 32 | `Dintpkt` | `dintpkt` | `reverse_direction` | `forbidden` | ❌ NO | Time elapsed between return packets. Requires reverse observation. Strictly prohibited. |
| 33 | `tcprtt` | `tcprtt` | `reverse_direction` | `forbidden` | ❌ NO | Explicit round-trip measurement requiring reverse SYN-ACK packet. Strictly prohibited. |
| 34 | `synack` | `synack` | `reverse_direction` | `forbidden` | ❌ NO | SYN-ACK travels in return direction. Strictly prohibited. |
| 35 | `ackdat` | `ackdat` | `bidirectional_or_future_dependent` | `forbidden` | ❌ NO | Requires knowing reverse SYN-ACK arrival time. Strictly prohibited. |
| 36 | `is_sm_ips_ports` | `is_sm_ips_ports` | `forward_observable` | `feature` | ✅ YES | Land attack indicator observable directly from forward packet IP/port headers. |
| 37 | `ct_state_ttl` | `ct_state_ttl` | `bidirectional_or_future_dependent` | `forbidden` | ❌ NO | Directly incorporates connection state which requires bidirectional tracking. |
| 38 | `ct_flw_http_mthd` | `ct_flw_http_mthd` | `forward_observable` | `feature` | ✅ YES | Client HTTP request methods are transmitted in the forward direction. |
| 39 | `is_ftp_login` | `is_ftp_login` | `bidirectional_or_future_dependent` | `forbidden` | ❌ NO | Verifying authenticated session status requires observing server reply code (230 vs 530). |
| 40 | `ct_ftp_cmd` | `ct_ftp_cmd` | `forward_observable` | `feature` | ✅ YES | Client FTP command invocations travel in the forward request stream. |
| 41 | `ct_srv_src` | `ct_srv_src` | `forward_observable` | `feature` | ✅ YES | Local sensor window aggregate over forward stream source addresses and requested services. |
| 42 | `ct_srv_dst` | `ct_srv_dst` | `forward_observable` | `feature` | ✅ YES | Local sensor window aggregate over forward destination addresses and requested services. |
| 43 | `ct_dst_ltm` | `ct_dst_ltm` | `forward_observable` | `feature` | ✅ YES | Local forward stream fan-in indicator. |
| 44 | `ct_src_ ltm` | `ct_src_ltm` | `forward_observable` | `feature` | ✅ YES | Local forward stream fan-out indicator. |
| 45 | `ct_src_dport_ltm` | `ct_src_dport_ltm` | `forward_observable` | `feature` | ✅ YES | Forward stream port-scanning / horizontal reconnaissance indicator. |
| 46 | `ct_dst_sport_ltm` | `ct_dst_sport_ltm` | `forward_observable` | `feature` | ✅ YES | Forward stream vertical reconnaissance indicator. |
| 47 | `ct_dst_src_ltm` | `ct_dst_src_ltm` | `forward_observable` | `feature` | ✅ YES | Forward stream host-pair connection density indicator. |
| 48 | `attack_cat` | `eval_label` | `identifier_or_grouping_only` | `label` | ❌ NO | Ground-truth attack annotation. Exclusively for post-prediction evaluation. Prohibited from training/inference. |
| 49 | `Label` | `is_attack` | `identifier_or_grouping_only` | `label` | ❌ NO | Ground-truth binary label. Exclusively for post-prediction evaluation. Prohibited from model input. |
