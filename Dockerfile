# syntax=docker/dockerfile:1.6
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# Install only the runtime deps from pyproject — no Playwright in the
# Cloud Run image; the admin frontend is read-only and does not scrape.
COPY pyproject.toml README.md ./
COPY app ./app
COPY data ./data
COPY scripts ./scripts

RUN pip install --upgrade pip && pip install \
    "fastapi>=0.116.0,<1.0.0" \
    "httpx>=0.28.0,<1.0.0" \
    "jinja2>=3.1.0,<4.0.0" \
    "uvicorn>=0.35.0,<1.0.0" \
    "pydantic>=2.0.0,<3.0.0"

EXPOSE 8080

# Cloud Run sets $PORT; default 8080 for local docker run.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
