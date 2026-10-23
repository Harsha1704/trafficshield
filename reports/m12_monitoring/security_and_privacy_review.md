# TrafficShield Security & Privacy Review: Monitoring Subsystem

**Milestone:** M12 — Intelligent Monitoring, Drift Detection & Model Lifecycle  
**Repository:** `D:\projects\TrafficShield`  
**Date:** 2026-10-23  

---

## 1. Threat Modeling & Security Posture

The introduction of monitoring telemetry and model registry controls introduces new operational threat surfaces. A structured STRIDE review was conducted to identify and mitigate risks:

| Threat Category | Potential Attack Vector | TrafficShield Mitigation |
|:---|:---|:---|
| **Tampering** | Replacing production `.joblib` model artifact with a backdoored classifier. | Every model entry is cryptographically anchored to its SHA-256 hash. The API verifies artifact hashes on startup. |
| **Tampering** | Model poisoning via automated continuous retraining on poisoned link traffic. | **Zero Automated Retraining:** Retraining on unlabelled traffic is architecturally forbidden. Retraining requires verified offline datasets. |
| **Elevation of Privilege** | Arbitrary or unauthorized promotion of unvalidated candidate models. | The registry endpoint (`POST /api/v1/monitoring/registry/promote`) enforces validation verification, requires approval metadata, and blocks unvalidated candidates. |
| **Denial of Service** | Exhausting server memory via unbounded batches sent to `/drift/evaluate`. | Batch size is capped at 5,000 records (`HTTP 413: PAYLOAD_TOO_LARGE`). |
| **Information Disclosure** | Storing sensitive packet payloads or CryptoPan IPs in database logs. | **Aggregate Telemetry:** Only non-sensitive statistical moments (mean, std, decile arrays) are persisted. Zero raw payloads are retained. |
| **Spoofing / False Metrics** | Injecting demonstration alerts or fixtures into production SOC dashboards. | Demo seeder endpoints (`seed-demo`) are physically blocked in production mode (`HTTP 403: FORBIDDEN_IN_PRODUCTION`). |

---

## 2. Privacy & Data Minimization Analysis

Under data minimization guidelines (e.g. GDPR Article 5(1)(c)):
1. **Zero Raw Packet Storage:** The monitoring subsystem never stores raw packet headers, payload bytes, or unencrypted user communications.
2. **Identifier Stripping:** Model features are forward-observable numeric transport metrics (`duration_seconds`, `fwd_bytes`, `sttl`, etc.). Source and destination IP addresses are excluded from model features and monitoring metric tables.
3. **Database Retention:** Configurable retention periods (`MONITORING_RETENTION_DAYS = 30`) automatically prune stale batch summaries, ensuring database storage does not grow indefinitely.

---

## 3. Administrative Prerequisites & Authentication Disclosure

### Current State
In the current development sprint, TrafficShield runs within a protected local network environment:
- CORS is strictly restricted to designated local development origins (`http://localhost:5173`, `http://127.0.0.1:5173`, `http://localhost:3000`).
- Flask development mode runs locally on `127.0.0.1`.

### Production Deployment Prerequisite
Full enterprise role-based access control (RBAC), OAuth2 / JWT authentication, and TLS termination are scheduled for production containerization.
- **Safety Precaution:** Administrative endpoints (such as `POST /api/v1/monitoring/registry/promote` and `POST /api/v1/monitoring/seed-demo`) must **never** be exposed to unauthenticated public networks without an API gateway or reverse proxy enforcing authentication.
