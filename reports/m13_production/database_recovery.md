# TrafficShield — Database Lifecycle & Disaster Recovery Guide

**Milestone:** M13 (Production Deployment, Security Hardening & Release Readiness)  
**Date:** 2026-10-23  
**Status:** Approved & Verified

---

## 1. Overview & Architecture Selection

TrafficShield stores persistent operational SOC records across seven relational tables:
1. `users` — Analyst and administrator identities, scrypt/pbkdf2 password hashes, roles, and login audit timestamps.
2. `security_alerts` — Durable security anomaly detections, analyst investigation notes, status workflows, and feature attributions.
3. `monitoring_batch_metrics` — Aggregate operational telemetry, score histograms, latency records, and feature metrics per scoring batch.
4. `monitoring_alerts` — Operational drift, rate spike, and latency degradation alerts with debouncing and deduplication counters.
5. `ground_truth_feedbacks` — Verified ground-truth investigation labels segregated from unverified analyst dispositions.
6. `model_registry_entries` — Governed model version ledger, threshold provenance, and promotion approval audit logs.
7. `system_events` — Low-level application factory audit trail.

---

## 2. Database Engine Characteristics & Boundaries

### 2.1. SQLite (Development & Single-Process Local Deployment)
- **Appropriate Use:** Local development, automated testing (`:memory:`), and single-host standalone workstations running a single WSGI process.
- **Operational Boundaries:**
  - **Concurrency:** SQLite uses database-level locking. While Write-Ahead Logging (WAL) permits concurrent readers, only a single write transaction can execute at any instant. Under multi-worker WSGI servers (e.g. Gunicorn with multiple worker processes), concurrent alert updates can cause `sqlite3.OperationalError: database is locked`.
  - **Storage:** Local filesystem file (`trafficshield_dev.db`). Never mount on network filesystems (NFS/SMB) due to lock-coherence bugs.
  - **Production Verdict:** Strictly forbidden in production (`ProductionSettings.db_must_not_be_sqlite` enforces this constraint at startup).

### 2.2. PostgreSQL 16+ (Production Standard)
- **Appropriate Use:** All multi-user, containerized, and production SOC environments.
- **Advantages:** Row-level locking (MVCC), ACID transactions, point-in-time recovery (PITR), connection pooling, high concurrent write throughput.
- **Connection URI Format:**
  ```text
  postgresql://trafficshield_user:<STRONG_PASSWORD>@<DB_HOST>:5432/trafficshield_prod
  ```

---

## 3. SQLite Backup & Recovery Procedure

TrafficShield includes an online, non-blocking backup procedure that avoids taking the server offline or copying partially-written files.

### 3.1. Online Backup Command (Python API)
```python
import sqlite3
from pathlib import Path

def backup_sqlite(source_db: Path, backup_dest: Path):
    """Perform online, transactionally consistent backup using SQLite Backup API."""
    src = sqlite3.connect(source_db)
    dest = sqlite3.connect(backup_dest)
    with dest:
        src.backup(dest, pages=100)
    dest.close()
    src.close()
    print(f"Backup successfully written to {backup_dest}")
```

### 3.2. Online Backup Command (CLI)
```bash
sqlite3 trafficshield_dev.db ".backup 'backups/trafficshield_backup_$(date +%Y%m%d_%H%M%S).db'"
```

### 3.3. Restoration Procedure
1. Stop the application server (`run.py` or `run_waitress.py`).
2. Move corrupt/damaged database file to a quarantine directory:
   ```bash
   mv trafficshield_dev.db trafficshield_dev.db.corrupted.$(date +%s)
   ```
3. Copy validated backup file to the target database location:
   ```bash
   cp backups/trafficshield_backup_20261023_120000.db trafficshield_dev.db
   ```
4. Verify file integrity:
   ```bash
   sqlite3 trafficshield_dev.db "PRAGMA integrity_check;"
   ```
5. Restart application server.

---

## 4. PostgreSQL Production Backup & Recovery

### 4.1. Scheduled Logical Backups (`pg_dump`)
Run daily logical backups using compressed custom format (`-Fc`):
```bash
#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="/var/backups/trafficshield"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/trafficshield_prod_${TIMESTAMP}.dump"

mkdir -p "${BACKUP_DIR}"

# Execute dump using PostgreSQL password authentication
PGPASSWORD="${POSTGRES_PASSWORD}" pg_dump \
  -h "${DB_HOST:-localhost}" \
  -U "${POSTGRES_USER:-trafficshield_user}" \
  -d "${POSTGRES_DB:-trafficshield_prod}" \
  -Fc \
  -f "${BACKUP_FILE}"

echo "Backup completed: ${BACKUP_FILE}"

# Retain backups for 30 days
find "${BACKUP_DIR}" -name "trafficshield_prod_*.dump" -mtime +30 -delete
```

### 4.2. Disaster Restoration (`pg_restore`)
In the event of database failure or corrupted state:
1. Stop application traffic to prevent incoming write transactions.
2. Re-create or prepare clean target database:
   ```bash
   dropdb -h localhost -U postgres trafficshield_prod
   createdb -h localhost -U postgres -O trafficshield_user trafficshield_prod
   ```
3. Restore from selected custom dump:
   ```bash
   PGPASSWORD="${POSTGRES_PASSWORD}" pg_restore \
     -h "${DB_HOST:-localhost}" \
     -U "${POSTGRES_USER:-trafficshield_user}" \
     -d trafficshield_prod \
     --clean \
     --if-exists \
     --no-owner \
     /var/backups/trafficshield/trafficshield_prod_20261023_120000.dump
   ```
4. Verify table counts and integrity:
   ```bash
   psql -h localhost -U trafficshield_user -d trafficshield_prod -c "\dt"
   psql -h localhost -U trafficshield_user -d trafficshield_prod -c "SELECT count(*) FROM security_alerts;"
   psql -h localhost -U trafficshield_user -d trafficshield_prod -c "SELECT count(*) FROM model_registry_entries;"
   ```
5. Run readiness probe:
   ```bash
   curl -f http://localhost:5000/api/v1/ready
   ```

---

## 5. Verification & Test Evidence

The online backup and restoration lifecycle was verified programmatically in the test suite:
- **Test File:** `tests/unit/test_m13_production_security.py`
- **Test Case:** `TestDisposableDatabaseRecovery::test_sqlite_online_backup_and_recovery_roundtrip`
- **Result:** **PASSED (100% verified)**
- **Verification Details:** The test instantiated a temporary SQLite database, populated records, created an online backup via `conn.backup`, destroyed active records (simulating database loss), restored all tables into a clean target database, and validated 100% data fidelity.
