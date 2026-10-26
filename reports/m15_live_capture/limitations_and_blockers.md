# TrafficShield M15 — Operational Limitations & Driver Blockers

**Document ID:** TS-M15-BLOCKERS  
**Date:** 2026-10-26  
**Status:** RESOLVED (PASS)  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Scope:** Transparent disclosure of hardware/driver prerequisites, security boundaries, protocol scopes, and architectural limitations.

---

## 1. Driver Blocker Status: RESOLVED

The previously documented driver blocker on this host is **RESOLVED**:
- **Npcap Driver:** Successfully installed with WinPcap API-compatible mode enabled.
- **Library Presence:** `wpcap.dll` and `Packet.dll` verified in `C:\Windows\System32`.
- **Interface Access:** Scapy successfully binds to Windows NPF device for Realtek RTL8852BE WiFi 6 PCIe adapter (`Wi-Fi`).
- **Live Ingestion Verified:** 8,259 live packets captured passively, 757 directional flows constructed, 668 scored by the frozen XGBoost detector, and 241 deduplicated alerts persisted to SQLite.

---

## 2. Security & Operational Boundaries

1. **No Promiscuous Sniffing by Default:**
   TrafficShield requires explicit operator selection of the network interface (`interface="Wi-Fi"`). It will never bind to interfaces indiscriminately.
2. **Passive-Only Out-of-Band Architecture:**
   TrafficShield is architected strictly as an out-of-band passive monitor:
   - Zero packet transmission or echoing back to the network.
   - Zero inline packet modification, blocking, or RST injection.
   - Designed for observation of unidirectional optical link taps, SPAN/mirror ports, or host wireless links.
3. **Payload Zero-Retention Policy:**
   TrafficShield discards all packet application payloads immediately after protocol header validation. No raw wire bytes or packet payloads are logged, buffered, or retained in memory or disk.
4. **Privilege Requirements:**
   On Windows, opening promiscuous capture interfaces requires membership in the local `Administrators` group or Npcap configured for non-admin access.

---

## 3. Protocol & Feature Scope Limitations

1. **IPv4 Monitored Traffic:**
   The frozen production model (`OptunaTuned_XGBoost`) was trained on IPv4 flow telemetry. IPv6 packets observed on live interfaces are categorized as `UNSUPPORTED_IP_VERSION_6` by `IPv4PacketValidator` and discarded without accumulating memory or corrupting IPv4 flow tables.
2. **Directional Flow Reconstruction:**
   In unidirectional monitoring, reverse traffic (e.g. server acknowledgments, response payloads, server TTL) is unobservable. Flows represent forward-only transactions.
3. **Incompatible Flow Rejection:**
   Packets or flows with corrupted headers, truncated IP payloads, or missing/zero TTL ($sttl \le 0$) are flagged `is_compatible = False` and dropped prior to inference, incrementing `incompatible_flows_rejected`.
