# Urban Farming backend — FastAPI on Cloud Run (or docker-compose locally).
#
# Build:  docker build -t urban-farming-backend .
# Run:    docker run --env-file .env -p 8000:8080 urban-farming-backend
# Config: all settings come from environment variables — see .env.example for
#         the full list (Supabase keys, DATA_BACKEND/AUTH_MODE, SMTP, etc.).

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

RUN pip install --no-cache-dir uv

# Install pinned dependencies from the lockfile first so this layer is cached
# across app-code changes.
COPY pyproject.toml uv.lock README.md ./
RUN uv export --frozen --no-dev --no-emit-project --format requirements-txt -o requirements.txt \
    && uv pip install --system --no-cache -r requirements.txt

COPY app ./app
RUN uv pip install --system --no-cache --no-deps .

USER 65532:65532
EXPOSE 8080

# Cloud Run ignores this; docker-compose and plain docker use it.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os,urllib.request;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8080\")}/health/live')"]

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
