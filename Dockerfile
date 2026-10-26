# Production Dockerfile for SOGo 6 Server
# Multi-stage build: builder → production

# ---- Builder Stage ----
FROM python:3.14-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    libldap2-dev \
    libsasl2-dev \
    libxml2-dev \
    libxmlsec1-dev \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=off

# Install pip packages in one layer (uses pyproject.toml for deps)
COPY pyproject.toml ./

# Install all runtime dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
        flask flask-compress flask-cors flask-smorest \
        gunicorn celery \
        prometheus-client authlib pyotp qrcode[pil] webauthn \
        marshmallow icalendar \
        psycopg[binary] mysql-connector-python==9.5.0 python-ldap redis \
        cryptography pyjwt pydantic pydantic-settings \
        sievelib yarl debugpy pysaml2 \
    # pinned upgrade line must be shell-quoted: unquoted '>=' is parsed as a
    # stdout redirection by bash, silently skipping the intended constraint
    && pip install --no-cache-dir --upgrade 'msgpack>=1.2.1' 'urllib3>=2.8.0' 'setuptools>=78.1.1' \
    && rm -rf /root/.cache/pip

# Copy source
COPY . .

# ---- Production Stage ----
FROM python:3.14-slim

WORKDIR /app

# Install runtime system dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    libldap2 \
    libsasl2-2 \
    xmlsec1 \
    libxml2 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_ENV=production \
    PIP_NO_CACHE_DIR=off

# Copy Python packages and app code from builder
COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /build/app /app/app

# Create log directory and non-root user
RUN mkdir -p /var/log/sogo /var/lib/sogo6 && \
    addgroup --system --gid 1001 sogo && \
    adduser --system --uid 1001 --ingroup sogo --home /app sogo && \
    chown -R sogo:sogo /app /var/log/sogo /var/lib/sogo6

USER sogo

EXPOSE 5000

# Health check — use 127.0.0.1 (not localhost, Alpine resolves ::1 IPv6)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://127.0.0.1:5000/api/user/v1/health || exit 1

# Run with gunicorn in production.
# gthread (not sync): /api/sse streams block a thread, not a whole worker —
# sync workers get WORKER TIMEOUT-killed by every SSE client.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "--threads", "4", \
     "--worker-class", "gthread", "--timeout", "120", \
     "--access-logfile", "-", "--error-logfile", "-", \
     "app.run:app"]
