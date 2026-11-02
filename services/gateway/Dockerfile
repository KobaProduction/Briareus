FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy
WORKDIR /app
COPY services/gateway/pyproject.toml /app/pyproject.toml
COPY services/gateway/uv.lock /app/uv.lock
COPY services/gateway/.python-version /app/.python-version
RUN uv sync --frozen --no-dev --no-install-project
RUN useradd -u 1000 -m -d /home/bridge bridge
COPY services/gateway/src/ /app/src/
COPY shared/gateway_runtime/ /app/src/gateway_runtime/
COPY shared/node_protocol/ /app/src/node_protocol/
COPY shared/runtime_peer/ /app/src/runtime_peer/
COPY shared/service_runtime/__init__.py shared/service_runtime/_reference_bindings.py shared/service_runtime/_field_serialization.py /app/src/service_runtime/
WORKDIR /app/src
USER 1000:1000
EXPOSE 8000
CMD ["uv", "run", "--frozen", "--no-sync", "--no-dev", "--project", "/app", "--directory", "/app/src", "uvicorn", "bridge.server:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1", "--no-access-log", "--timeout-graceful-shutdown", "10"]
