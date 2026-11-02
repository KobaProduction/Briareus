FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy PYTHONPATH=/app/src
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates gosu netcat-openbsd && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
RUN mkdir -p /var/lib/bri/control-panel /var/lib/bri/oauth /workspace /browser/profile /home/agent /home/bri && chown -R 1000:1000 /var/lib/bri /workspace /browser /home/agent /home/bri
ENV HOME=/home/bri
EXPOSE 8000
ENTRYPOINT ["/usr/sbin/gosu", "1000:1000"]
CMD ["/app/.venv/bin/python", "-m", "common.asgi"]
