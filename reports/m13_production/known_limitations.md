# TrafficShield M13 — Known Limitations & Operational Boundaries

**Milestone:** M13 (Production Deployment, Security Hardening & Release Readiness)  
**Date:** 2026-10-23  
**Status:** Defensible Technical Documentation

---

## 1. Observability & Detection Scope Boundaries

1. **Unidirectional Link Observability Scope:**
   - TrafficShield is architecturally restricted to one-way monitoring links (such as unidirectional network taps, unidirectional security gateways, or ISP border interfaces).
   - The system **cannot observe** reverse-direction traffic: return ACKs, round-trip times (RTT), TCP handshake completions, or bidirectional byte ratios.
   - Any attempt to feed bidirectional ARGUS or CICFlowMeter backward features into inference is rejected at the API layer by the causal policy engine.

2. **Cross-Dataset Generalization Boundaries:**
   - Authoritative benchmarks are verified strictly on the **UNSW-NB15** dataset:
     - Day 1 Held-Out Test: 98.10% accuracy, 97.78% recall, 0.9987 ROC-AUC.
     - Day 2 Temporal Holdout: 96.97% accuracy, 98.37% recall (evaluated 24 days later).
   - As established in Milestone 10.1, raw **CICIDS2017** data is absent locally (0 MB). Direct zero-shot model transfer to different network topologies without local sensor calibration is **not supported**. Cross-network deployments require collecting calibration baseline flows from the target environment.

---

## 2. Platform & Deployment Limitations

1. **Windows Host vs Containerized Deployment:**
   - On Linux hosts and in Docker containers, TrafficShield runs on **Gunicorn** with multi-threaded workers (`gthread`) and POSIX signal handling.
   - On native Windows environments without Docker, Gunicorn cannot execute due to missing `fcntl` and Unix signal primitives. Windows hosts must execute the provided **Waitress** WSGI runner (`python run_waitress.py`).

2. **Windows Smart App Control & Python 3.14:**
   - Under Windows 11 Smart App Control / WDAC, certain standalone C-extensions (such as scikit-learn's `_sag_fast`) may be blocked if executed directly from custom standalone scripts without a clean interpreter context. Pytest and Waitress execute within certified Python runner contexts where all 418 tests pass cleanly.

---

## 3. Database & Concurrency Limitations

1. **SQLite Concurrency Limits:**
   - The default development database uses SQLite (`trafficshield_dev.db`).
   - While SQLite Write-Ahead Logging (WAL) permits concurrent readers, write operations require exclusive table-level locks. Under high-concurrency multi-worker Gunicorn deployments, simultaneous alert ingestion will encounter `database is locked` errors.
   - **Production Requirement:** SQLite is strictly rejected by `ProductionSettings`. Production deployments must use **PostgreSQL 16+**.

2. **Distributed Rate Limiting:**
   - In default single-host configurations, `Flask-Limiter` stores request counts in memory (`memory://`).
   - In a horizontally scaled cluster with multiple container replicas, rate limits are enforced per-container rather than globally. Clustered deployments must configure Redis via `RATELIMIT_STORAGE_URL=redis://redis:6379/0`.

---

## 4. Identity & Access Management Boundaries

1. **Local Authentication vs Enterprise SSO:**
   - TrafficShield provides internal, database-backed authentication and RBAC supporting `analyst` and `admin` roles, secure scrypt/PBKDF2 hashing, and signed session tokens.
   - Enterprise federated identity standards (SAML 2.0, OpenID Connect, Okta, Active Directory) are not natively built into the core API. For enterprise SSO, TrafficShield should be deployed behind an authenticating reverse proxy (such as OAuth2-Proxy or Nginx with `auth_request`) forwarding validated identity headers.

2. **Analyst Feedback vs Ground-Truth:**
   - Analyst investigation dispositions (`analyst_disposition`: `'SUSPICIOUS_UNVERIFIED'`) are strictly segregated from verified ground truth.
   - TrafficShield **never automatically retrains** or adjusts decision boundaries based on unverified analyst notes or unlabeled live traffic.
