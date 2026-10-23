# TrafficShield M14 — Known Operational Limitations & Boundaries

**Milestone:** M14 — End-to-End Release Validation  
**Date:** 2026-10-23  
**Status:** Defensible Engineering Documentation  

---

## 1. Scope & Purpose

In alignment with TrafficShield's core engineering principles of scientific truthfulness and evidence provenance, this document outlines the verified boundaries, physical assumptions, and operational constraints of the platform.

---

## 2. Identified Operational Boundaries

### 1. Live Kernel Packet Capture Driver Dependency (Windows Npcap)
- **Constraint:** Live promiscuous interface sniffing on Windows requires native WinPcap/Npcap kernel drivers (`wpcap.dll` / `Packet.dll`).
- **Host Status:** On the current Windows test host, native Npcap DLLs are not installed; Scapy warns: `WARNING: No libpcap provider available ! pcap won't be used`.
- **System Impact:** Live interface capture is driver-blocked on this host; however, **offline PCAP replay (`rdpcap`)**, **pure-Python packet aggregation**, and **REST API flow ingestion** operate with 100% mathematical fidelity.
- **Production Recommendation:** When deploying on Windows sensors for live network wire tapping, install Npcap with the *"Install Npcap in WinPcap API-compatible Mode"* option enabled. On Linux sensors, standard `libpcap-dev` is supported natively.

### 2. Single-Packet Flow Observability Boundaries
- **Constraint:** When a network flow consists of exactly one forward packet ($N=1$), the elapsed time between the first and last packet is identically 0.0 seconds ($t_{\text{last}} - t_{\text{first}} = 0.0$).
- **Mathematical Handling:** Time-dependent rate features cannot divide by zero. TrafficShield strictly guards these features:
  - `duration_seconds` $= 0.0$
  - `sload` $= 0.0\text{ bps}$
  - `packet_rate` $= 0.0\text{ pkt/s}$
  - `byte_rate` $= 0.0\text{ B/s}$
  - `sjit` (jitter) $= 0.0\text{ ms}$
  - `sintpkt` (inter-packet interval) $= 0.0\text{ ms}$
- **Model Behavior:** The frozen Random Forest detector evaluates single-packet flows based on `sttl`, `swin`, `smeansz`, `fwd_bytes`, and `is_sm_ips_ports`. Single-packet port scans (e.g., SYN-only probes) are successfully detected through size and TCP header features.

### 3. Intentional Unidirectional Blindness
- **Design Premise:** TrafficShield is built for optical taps and data diodes that observe forward-link traffic only.
- **Physical Boundary:** The platform cannot observe return-path packets (SYN-ACK, return RSTs, ACK payloads). Consequently:
  - It cannot verify whether an outbound TCP connection succeeded or was rejected by the remote server.
  - It cannot compute round-trip time (RTT) or request-response latency.
  - It cannot observe server HTTP status codes or return error banners.
- **Mitigation:** Unidirectional behavioural modeling focuses entirely on outbound volume, packet timing patterns, port distribution, and TCP window dynamics.

### 4. Sample Size Minimums for Statistical Drift Detection
- **Constraint:** Population Stability Index (PSI) calculation on small sample sets produces unstable, highly noisy divergence metrics.
- **System Policy:** TrafficShield enforces a strict **Sample Size Guard** requiring a minimum of **500 flows** per monitoring window before computing PSI drift metrics.
- **Operational Behavior:** Batches containing fewer than 500 flows return `status: "INSUFFICIENT_DATA"` with a descriptive disclaimer rather than emitting false drift alarms.

### 5. SQLite Persistence Concurrency Thresholds
- **Constraint:** The bundled SQLite database engine utilizes Write-Ahead Logging (WAL) mode, providing high read concurrency and robust crash recovery.
- **Throughput Boundary:** SQLite enforces serialized single-writer locking. It comfortably handles hundreds of alert insertions and monitoring updates per second.
- **Enterprise Upgrade Path:** In high-volume environments exceeding $\approx 5,000$ alert writes/second, configure `DATABASE_URL` in `.env` to point to an external PostgreSQL cluster (`postgresql://user:pass@host:5432/trafficshield`). The SQLAlchemy ORM models require zero code changes.
