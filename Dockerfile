# Multi-stage Dockerfile for NexOps
# Stage 1: Build the React frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /build

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# Stage 2: Python backend runtime
FROM python:3.12-slim AS runner

WORKDIR /app

# Prevent Python from writing .pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    APP_HOST=0.0.0.0

# Install system dependencies (curl for healthchecks, libpq for postgres)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:0.5.21 /uv /uvx /bin/

# Copy dependency specifications and lockfile
COPY pyproject.toml uv.lock ./

# Install Python dependencies into system environment
RUN uv sync --frozen --no-dev --no-install-project

# Copy application source code
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY alembic.ini ./

# Copy built frontend assets from stage 1
COPY --from=frontend-builder /build/dist ./frontend/dist

EXPOSE 8000

# Healthcheck probing the API health endpoint
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
