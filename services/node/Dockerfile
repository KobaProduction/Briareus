FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy
# Fixed one-shot network-policy helpers use these only inside the dedicated
# rootless daemon namespace; normal Agent/Gateway/worker containers have no
# NET_ADMIN capability and cannot change rules.
RUN apt-get update && apt-get install -y --no-install-recommends iptables iproute2 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY services/node/pyproject.toml services/node/uv.lock /app/
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY services/node/src/ /app/src/
COPY shared/node_protocol/ /app/src/node_protocol/
COPY shared/gateway_runtime/ /app/src/gateway_runtime/
COPY shared/service_runtime/__init__.py shared/service_runtime/runtime_binding.py /app/src/service_runtime/
RUN useradd --uid 2201 --create-home node
WORKDIR /app/src
USER 2201:2201
EXPOSE 8080
CMD ["/app/.venv/bin/python", "-m", "node_agent.server"]
