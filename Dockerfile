# Development/contract image only. Product images belong to services/<owner>/Dockerfile.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends chromium curl ca-certificates fonts-liberation fonts-noto-color-emoji xvfb && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --group web --group quality
ENTRYPOINT ["/app/.venv/bin/python"]
