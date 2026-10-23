# syntax=docker/dockerfile:1
# ─────────────────────────────────────────────────────────────────────────────
# TrafficShield Production Multi-Stage Containerfile
# Milestone 13 — Production Deployment, Security Hardening & Release Readiness
# ─────────────────────────────────────────────────────────────────────────────

# ─── Stage 1: Frontend Build ─────────────────────────────────────────────────
FROM node:22-alpine AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ─── Stage 2: Production Python Runtime ──────────────────────────────────────
FROM python:3.12-slim AS production-runtime

# Harden container environment
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=5000 \
    FLASK_ENV=production \
    APP_ENV=production

# Install essential runtime system libraries & security updates
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root dedicated application service account
RUN groupadd -g 10001 trafficshield && \
    useradd -u 10001 -g trafficshield -s /bin/bash -m trafficshield

WORKDIR /app

# Install Python production requirements
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt gunicorn

# Copy application source code and verified artifacts
COPY app/ app/
COPY config/ config/
COPY features/ features/
COPY ml/ ml/
COPY monitoring/ monitoring/
COPY artifacts/ artifacts/
COPY run.py gunicorn_conf.py ./

# Copy built frontend assets into static web root
COPY --from=frontend-builder /app/frontend/dist /app/frontend_dist

# Set strict file ownership to non-root user
RUN chown -R trafficshield:trafficshield /app

# Drop root privileges
USER trafficshield

# Expose internal WSGI port
EXPOSE 5000

# Container liveness health check via lightweight health probe
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:5000/api/v1/health || exit 1

# Start production WSGI server
CMD ["gunicorn", "-c", "gunicorn_conf.py", "run:app"]
