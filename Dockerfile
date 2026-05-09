# ── Cairo Smart Transportation System — Dockerfile ──────────────────────────
# Multi-stage build: keeps final image lean (~350 MB)

# ── Stage 1: build / install dependencies ────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# System deps for scikit-learn (BLAS)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libgomp1 && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt

# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM python:3.11-slim

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# OpenMP runtime (needed by scikit-learn RandomForest)
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy application source
COPY src/         ./src/
COPY data/        ./data/
COPY templates/   ./templates/
COPY static/      ./static/
COPY models/      ./models/

# Create models directory if not present
RUN mkdir -p models

# Environment
ENV PYTHONPATH=/app/src
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=5000

EXPOSE 5000

# Pre-train ML models at image build time (optional but speeds up cold start)
# Uncomment if you want models baked into the image:
# RUN python src/ml_prediction.py

# Entrypoint: gunicorn production server
CMD ["gunicorn", \
     "--chdir", "src", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "2", \
     "--threads", "4", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "app:app"]
