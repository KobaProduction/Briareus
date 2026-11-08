# BEGIN BRIAREUS PYTHON RUNTIME
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS python-runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy PYTHONPATH=/app/src
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates gosu netcat-openbsd && rm -rf /var/lib/apt/lists/*
COPY services/hands/analysis/system-packages.txt /tmp/service-packages.txt
RUN apt-get update && xargs -r apt-get install -y --no-install-recommends < /tmp/service-packages.txt && rm -rf /var/lib/apt/lists/* /tmp/service-packages.txt
COPY services/hands/analysis/pyproject.toml services/hands/analysis/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
RUN mkdir -p /var/lib/briareus/control-panel /workspace /browser/profile /home/agent /home/briareus && chown -R 1000:1000 /var/lib/briareus /workspace /browser /home/agent /home/briareus
ENV HOME=/home/briareus
EXPOSE 8000
ENTRYPOINT ["/usr/sbin/gosu", "1000:1000"]
CMD ["/app/.venv/bin/python", "-m", "briareus_service_runtime.asgi"]
# END BRIAREUS PYTHON RUNTIME
# Native engine versions are pinned independently of Briareus source changes.
ARG RADARE2_COMMIT=133aeff15cc6a1f679b8c93bcdc9206f9a411fe3
ARG R2MCP_COMMIT=562c0cf23c42b65b3052f0b294d8778c20facbde
RUN git init /tmp/radare2 && git -C /tmp/radare2 remote add origin https://github.com/radareorg/radare2.git && git -C /tmp/radare2 fetch --depth 1 origin "$RADARE2_COMMIT" && git -C /tmp/radare2 checkout FETCH_HEAD && cd /tmp/radare2 && ./configure --prefix=/usr/local && make -j2 && make install && ldconfig && rm -rf /tmp/radare2
RUN git init /tmp/r2mcp && git -C /tmp/r2mcp remote add origin https://github.com/radareorg/radare2-mcp.git && git -C /tmp/r2mcp fetch --depth 1 origin "$R2MCP_COMMIT" && git -C /tmp/r2mcp checkout FETCH_HEAD && cd /tmp/r2mcp && ./configure --prefix=/usr/local && make -j2 && make install && ldconfig && rm -rf /tmp/r2mcp
# BEGIN BRIAREUS SOURCE PACKAGES
COPY services/hands/analysis/src/briareus_analyzer /app/src/briareus_analyzer
COPY shared/cache/src/briareus_cache /app/src/briareus_cache
COPY shared/contracts/accounts/src/briareus_account_contracts /app/src/briareus_account_contracts
COPY shared/contracts/http-surface/src/briareus_http_surface /app/src/briareus_http_surface
COPY shared/contracts/invocation-events/src/briareus_invocation_events /app/src/briareus_invocation_events
COPY shared/contracts/json-values/src/briareus_json_values /app/src/briareus_json_values
COPY shared/control_panel_client/src/briareus_control_panel_client /app/src/briareus_control_panel_client
COPY shared/hand_runtime/src/briareus_hand_runtime /app/src/briareus_hand_runtime
COPY shared/http_transport/src/briareus_http_transport /app/src/briareus_http_transport
COPY shared/mcp_client/src/briareus_mcp_client /app/src/briareus_mcp_client
COPY shared/python/environment-models/src/briareus_environment_models /app/src/briareus_environment_models
COPY shared/python/environment-parsing/src/briareus_environment_parsing /app/src/briareus_environment_parsing
COPY shared/server/workspace-mount/src/briareus_server_mount /app/src/briareus_server_mount
COPY shared/service_runtime/src/briareus_service_runtime /app/src/briareus_service_runtime
COPY shared/services/catalog/src/briareus_service_catalog /app/src/briareus_service_catalog
COPY shared/services/discovery/src/briareus_service_discovery /app/src/briareus_service_discovery
COPY shared/telemetry/src/briareus_telemetry /app/src/briareus_telemetry
# END BRIAREUS SOURCE PACKAGES
ENV ASGI_APP=briareus_analyzer.runtime:app
