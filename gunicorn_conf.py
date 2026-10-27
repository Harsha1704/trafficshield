"""
TrafficShield Production Gunicorn Configuration
================================================
Milestone 13 — Production Deployment, Security Hardening & Release Readiness

Optimized for high-throughput, low-latency asynchronous network anomaly scoring.
"""
import multiprocessing
import os

# Network binding
port = os.getenv("PORT", "5000")
bind = os.getenv("GUNICORN_BIND", f"0.0.0.0:{port}")
backlog = 2048

# Concurrency & Worker Model
# In production, recommend (2 * CPU_CORES) + 1 workers
default_workers = max(2, (multiprocessing.cpu_count() * 2) + 1)
workers = int(os.getenv("GUNICORN_WORKERS", default_workers))
worker_class = os.getenv("GUNICORN_WORKER_CLASS", "gthread")
threads = int(os.getenv("GUNICORN_THREADS", "4"))
worker_connections = 1000
timeout = int(os.getenv("GUNICORN_TIMEOUT", "60"))
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", "5"))

# Process management & worker recycling (prevents memory fragmentation)
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "5000"))
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", "500"))
graceful_timeout = 30

# Logging
loglevel = os.getenv("LOG_LEVEL", "info").lower()
accesslog = "-"  # stdout
errorlog = "-"   # stderr
access_log_format = (
    '{"remote_ip":"%(h)s","time":"%(t)s","method":"%(m)s","path":"%(U)s",'
    '"status":%(s)s,"bytes":%(b)s,"duration_ms":%(D)s,"request_id":"%({X-Request-ID}i)s"}'
)

# Security & Server Cloaking
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190
raw_env = [
    "PYTHONUNBUFFERED=1",
]


def on_starting(server):
    """Log startup banner with worker parameters."""
    server.log.info("Starting TrafficShield Production WSGI Server [Gunicorn]")
    server.log.info(f"Binding: {bind} | Workers: {workers} ({worker_class}, {threads} threads/worker)")


def worker_exit(server, worker):
    """Log worker termination."""
    server.log.info(f"Worker {worker.pid} exited cleanly.")
