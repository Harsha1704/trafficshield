# TrafficShield M14.1 — PCAP Replay Execution Evidence & Trace

**Milestone:** M14.1 — Forensic Model Identity, Feature Equivalence & Real-Time Evidence Audit  
**Date:** 2026-10-23  
**Auditor:** Antigravity  
**Repository:** `D:\projects\trafficshield`  
**Verdict:** **VERIFIED** (29 Packets -> 24 Flows -> Full Inference Scored)  

---

## 1. Executive Summary

This report presents verifiable, forensic proof of the execution of `data/captures/sample_traffic.pcap` through TrafficShield's real-time capture pipeline.

Every single packet was read by [`PcapReplaySource`](file:///D:/projects/trafficshield/ingestion/capture/pcap_source.py), aggregated into unidirectional flow states by [`UnidirectionalFlowBuilder`](file:///D:/projects/trafficshield/ingestion/flow/flow_builder.py), and scored by the production inference engine [`ProductionInferenceService`](file:///D:/projects/trafficshield/ml/production_service.py).

---

## 2. PCAP File Specifications & Checksums

| Attribute | Value |
| :--- | :--- |
| **File Path** | `data/captures/sample_traffic.pcap` |
| **File Size** | 2,752 bytes |
| **SHA-256 Checksum** | `68eecdbd5bbab8c5efb0e008ba82cf9df7ff3a25cb8aa06da09a9a08e1694df2` |
| **Magic Header** | `0xa1b2c3d4` (Standard libpcap microsecond format) |
| **Total Captured Packets** | 29 |

---

## 3. Packet Composition & Traffic Profile

The 29 packets within `sample_traffic.pcap` comprise 4 distinct traffic activities:

1. **Persistent TLS Stream (6 Packets):**
   - Source: `192.168.1.25:49152` $\to$ Destination: `104.244.42.1:443` (TCP)
   - Behavior: SYN, ACK, and TLS ClientHello / data segments.
   - Inter-arrival: 0.04s increments over 0.20s total duration.
2. **DNS Resolution Probes (2 Packets):**
   - Packets 7 & 8: `192.168.1.10:53530` and `:53531` $\to$ `8.8.8.8:53` (UDP).
   - Behavior: Isolated DNS query packets (1 packet per flow).
3. **Internal Loopback Probe (1 Packet):**
   - Packet 9: `192.168.1.50:8080` $\to$ `192.168.1.50:8080` (TCP SYN).
4. **Horizontal Port Scan Burst (20 Packets):**
   - Source: `10.10.10.100` (ephemeral ports `60000` through `60019`) $\to$ Destination: `192.168.1.1:80` (TCP SYN).
   - Behavior: 20 rapid single-packet probes with 0.005s inter-arrival spacing.

---

## 4. Complete Execution Trace & Model Scoring Output

When processed through the pipeline, the 29 packets yield exactly **24 finalized unidirectional flows**:

| Flow Index | Flow 5-Tuple Identifier | Protocol | Packets | Bytes | Duration (s) | Sload (bps) | Model Score | Risk Level | Anomaly? |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 0 | `192.168.1.25:49152->104.244.42.1:443` | TCP | 6 | 240 | 0.200000 | 9600.00 | **0.3681** | LOW | False |
| 1 | `192.168.1.10:53530->8.8.8.8:53` | UDP | 1 | 34 | 0.000000 | 0.00 | **0.1273** | LOW | False |
| 2 | `192.168.1.10:53531->8.8.8.8:53` | UDP | 1 | 34 | 0.000000 | 0.00 | **0.1273** | LOW | False |
| 3 | `192.168.1.50:8080->192.168.1.50:8080` | TCP | 1 | 40 | 0.000000 | 0.00 | **0.1273** | LOW | False |
| 4 | `10.10.10.100:60000->192.168.1.1:80` | TCP | 1 | 40 | 0.000000 | 0.00 | **0.1273** | LOW | False |
| 5 | `10.10.10.100:60001->192.168.1.1:80` | TCP | 1 | 40 | 0.000000 | 0.00 | **0.1273** | LOW | False |
| 6 | `10.10.10.100:60002->192.168.1.1:80` | TCP | 1 | 40 | 0.000000 | 0.00 | **0.1273** | LOW | False |
| 7 | `10.10.10.100:60003->192.168.1.1:80` | TCP | 1 | 40 | 0.000000 | 0.00 | **0.1273** | LOW | False |
| 8 | `10.10.10.100:60004->192.168.1.1:80` | TCP | 1 | 40 | 0.000000 | 0.00 | **0.1273** | LOW | False |
| 9 | `10.10.10.100:60005->192.168.1.1:80` | TCP | 1 | 40 | 0.000000 | 0.00 | **0.1273** | LOW | False |
| 10 | `10.10.10.100:60006->192.168.1.1:80` | TCP | 1 | 40 | 0.000000 | 0.00 | **0.1273** | LOW | False |
| 11 | `10.10.10.100:60007->192.168.1.1:80` | TCP | 1 | 40 | 0.000000 | 0.00 | **0.1273** | LOW | False |
| 12 | `10.10.10.100:60008->192.168.1.1:80` | TCP | 1 | 40 | 0.000000 | 0.00 | **0.1273** | LOW | False |
| 13 | `10.10.10.100:60009->192.168.1.1:80` | TCP | 1 | 40 | 0.000000 | 0.00 | **0.1273** | LOW | False |
| 14 | `10.10.10.100:60010->192.168.1.1:80` | TCP | 1 | 40 | 0.000000 | 0.00 | **0.1273** | LOW | False |
| 15 | `10.10.10.100:60011->192.168.1.1:80` | TCP | 1 | 40 | 0.000000 | 0.00 | **0.1273** | LOW | False |
| 16 | `10.10.10.100:60012->192.168.1.1:80` | TCP | 1 | 40 | 0.000000 | 0.00 | **0.1273** | LOW | False |
| 17 | `10.10.10.100:60013->192.168.1.1:80` | TCP | 1 | 40 | 0.000000 | 0.00 | **0.1273** | LOW | False |
| 18 | `10.10.10.100:60014->192.168.1.1:80` | TCP | 1 | 40 | 0.000000 | 0.00 | **0.1273** | LOW | False |
| 19 | `10.10.10.100:60015->192.168.1.1:80` | TCP | 1 | 40 | 0.000000 | 0.00 | **0.1273** | LOW | False |
| 20 | `10.10.10.100:60016->192.168.1.1:80` | TCP | 1 | 40 | 0.000000 | 0.00 | **0.1273** | LOW | False |
| 21 | `10.10.10.100:60017->192.168.1.1:80` | TCP | 1 | 40 | 0.000000 | 0.00 | **0.1273** | LOW | False |
| 22 | `10.10.10.100:60018->192.168.1.1:80` | TCP | 1 | 40 | 0.000000 | 0.00 | **0.1273** | LOW | False |
| 23 | `10.10.10.100:60019->192.168.1.1:80` | TCP | 1 | 40 | 0.000000 | 0.00 | **0.1273** | LOW | False |

---

## 5. Distinction Between Test Categories

To ensure compliance with audit requirements, we delineate three distinct testing scopes:

1. **Unit Test Fixtures (`tests/unit/test_m14_realtime_detection.py`):**
   - Uses dynamically generated Scapy packets in temporary directories to test boundary behaviors (e.g. FIN flag termination, LRU eviction, alert deduplication, driver absence).
2. **PCAP Replay Integration Test (`sample_traffic.pcap`):**
   - Validates that actual binary PCAP files on disk can be replayed, parsed, aggregated into flows, and scored by the production inference service without errors.
3. **Live Network Interface Sniffing:**
   - Evaluates whether real-time promiscuous sniffing on physical network adapters can occur.
   - Status: **NOT RUN (DRIVER BLOCKED)** due to absent `wpcap.dll` on this host. Cleanly reported via API without simulation.

---

## 6. Audit Verdict

| Verification Item | Expectation | Measured Result | Verdict |
| :--- | :--- | :--- | :--- |
| **Packet Parse Count** | Exactly 29 packets | 29 packets read | **VERIFIED** |
| **Flow Aggregation Count** | 24 finalized flows | Exactly 24 flows produced | **VERIFIED** |
| **Inference Path** | All flows evaluated by `OptunaTuned_XGBoost` | 24 scores generated, zero errors | **VERIFIED** |
| **Directional Separation** | Forward flows separated from return traffic | 100% forward 5-tuples | **VERIFIED** |
