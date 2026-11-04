# BEGIN BRIAREUS PYTHON RUNTIME
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS python-runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy PYTHONPATH=/app/src
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates gosu netcat-openbsd && rm -rf /var/lib/apt/lists/*
COPY services/hands/web/pyproject.toml services/hands/web/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
RUN mkdir -p /var/lib/briareus/control-panel /var/lib/briareus/oauth /workspace /browser/profile /home/agent /home/briareus && chown -R 1000:1000 /var/lib/briareus /workspace /browser /home/agent /home/briareus
ENV HOME=/home/briareus
EXPOSE 8000
ENTRYPOINT ["/usr/sbin/gosu", "1000:1000"]
CMD ["/app/.venv/bin/python", "-m", "briareus_service_runtime.asgi"]
# END BRIAREUS PYTHON RUNTIME
FROM node:22-bookworm-slim AS devtools
RUN npm install --global --prefix /opt/chrome-devtools-mcp chrome-devtools-mcp@1.10.1
FROM python-runtime
COPY --from=devtools /usr/local/bin/node /usr/local/bin/node
COPY --from=devtools /opt/chrome-devtools-mcp /opt/chrome-devtools-mcp
ENV CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS=1 CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS=1 CHROME_DEVTOOLS_MCP_NO_CONFIG_DISCOVERY=1
# BEGIN BRIAREUS SOURCE PACKAGES
COPY services/hands/web/src/briareus_web /app/src/briareus_web
COPY shared/browser/debug-tickets/src/briareus_browser_debug_tickets /app/src/briareus_browser_debug_tickets
COPY shared/cache/src/briareus_cache /app/src/briareus_cache
COPY shared/contracts/accounts/src/briareus_account_contracts /app/src/briareus_account_contracts
COPY shared/contracts/http-surface/src/briareus_http_surface /app/src/briareus_http_surface
COPY shared/contracts/invocation-events/src/briareus_invocation_events /app/src/briareus_invocation_events
COPY shared/contracts/json-values/src/briareus_json_values /app/src/briareus_json_values
COPY shared/contracts/tool-annotations/src/briareus_tool_annotations /app/src/briareus_tool_annotations
COPY shared/control-panel/browser-policy-client/src/briareus_browser_policy_client /app/src/briareus_browser_policy_client
COPY shared/control_panel_client/src/briareus_control_panel_client /app/src/briareus_control_panel_client
COPY shared/hand_runtime/src/briareus_hand_runtime /app/src/briareus_hand_runtime
COPY shared/http_transport/src/briareus_http_transport /app/src/briareus_http_transport
COPY shared/policies/browser/src/briareus_browser_policy /app/src/briareus_browser_policy
COPY shared/python/environment-models/src/briareus_environment_models /app/src/briareus_environment_models
COPY shared/python/environment-parsing/src/briareus_environment_parsing /app/src/briareus_environment_parsing
COPY shared/server/workspace-mount/src/briareus_server_mount /app/src/briareus_server_mount
COPY shared/service_runtime/src/briareus_service_runtime /app/src/briareus_service_runtime
COPY shared/telemetry/src/briareus_telemetry /app/src/briareus_telemetry
COPY shared/websocket_transport/src/briareus_websocket_transport /app/src/briareus_websocket_transport
COPY shared/workspace/src/briareus_workspace /app/src/briareus_workspace
# END BRIAREUS SOURCE PACKAGES
ENV ASGI_APP=briareus_web.runtime:app
RUN mkdir -p /tmp/briareus-browser-transfers && chown 1000:1000 /tmp/briareus-browser-transfers
