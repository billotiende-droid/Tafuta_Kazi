# ---------------------------------------------------------------------------
# Stage 1: dependency installation
# Using a separate build stage keeps the final image lean — build tools and
# pip cache are discarded and never shipped to Cloud Run.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /build

COPY requirements.txt .

# --no-cache-dir: don't store the pip download cache in the image layer
# --prefix: install into /install so we can copy just this directory later
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ---------------------------------------------------------------------------
# Stage 2: runtime image
# ---------------------------------------------------------------------------
FROM python:3.11-slim

WORKDIR /app

# Copy only the installed packages from the builder stage
COPY --from=builder /install /usr/local

# Copy application source — .dockerignore excludes venv, .env, *.db, output/
COPY . .

# Cloud Run injects PORT at runtime. The app reads settings.PORT which
# defaults to 8080 — matching Cloud Run's default expectation.
ENV PORT=8080

# Run as a non-root user. Cloud Run supports this and it is a security best
# practice — a compromised process cannot write outside /app.
RUN useradd --no-create-home --shell /bin/false appuser \
    && chown -R appuser:appuser /app
USER appuser

# Cloud Run expects the container to listen on $PORT and respond to HTTP.
# In webhook mode main.py starts the aiohttp server on that port.
CMD ["python", "main.py"]
