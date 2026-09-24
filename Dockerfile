FROM ghcr.io/astral-sh/uv:0.10.9 AS uv
FROM python:3.12-slim AS builder
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable
FROM python:3.12-slim
ENV PATH="/app/.venv/bin:$PATH" HOST=0.0.0.0 PORT=8000 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
RUN groupadd --system app && useradd --system --gid app app
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/healthz',timeout=2)"
CMD ["atlas-lyme-mcp"]
