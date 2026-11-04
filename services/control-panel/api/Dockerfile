# BEGIN BRIAREUS PYTHON RUNTIME
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS python-runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy PYTHONPATH=/app/src
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates gosu netcat-openbsd && rm -rf /var/lib/apt/lists/*
COPY services/control-panel/api/pyproject.toml services/control-panel/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
RUN mkdir -p /var/lib/briareus/control-panel /var/lib/briareus/oauth /workspace /browser/profile /home/agent /home/briareus && chown -R 1000:1000 /var/lib/briareus /workspace /browser /home/agent /home/briareus
ENV HOME=/home/briareus
EXPOSE 8000
ENTRYPOINT ["/usr/sbin/gosu", "1000:1000"]
CMD ["/app/.venv/bin/python", "-m", "briareus_service_runtime.asgi"]
# END BRIAREUS PYTHON RUNTIME
# BEGIN BRIAREUS SOURCE PACKAGES
COPY services/control-panel/api/src/auth_service /app/src/auth_service
COPY services/control-panel/api/src/briareus_identity /app/src/briareus_identity
COPY services/control-panel/api/src/control_panel_api /app/src/control_panel_api
COPY shared/browser/debug-tickets/src/briareus_browser_debug_tickets /app/src/briareus_browser_debug_tickets
COPY shared/cache/src/briareus_cache /app/src/briareus_cache
COPY shared/contracts/accounts/src/briareus_account_contracts /app/src/briareus_account_contracts
COPY shared/contracts/invocation-events/src/briareus_invocation_events /app/src/briareus_invocation_events
COPY shared/contracts/json-values/src/briareus_json_values /app/src/briareus_json_values
COPY shared/contracts/mcp-resources/src/briareus_mcp_resources /app/src/briareus_mcp_resources
COPY shared/contracts/oauth-sessions/src/briareus_oauth_sessions /app/src/briareus_oauth_sessions
COPY shared/control-panel/oauth-sessions-client/src/briareus_oauth_sessions_client /app/src/briareus_oauth_sessions_client
COPY shared/control_panel_client/src/briareus_control_panel_client /app/src/briareus_control_panel_client
COPY shared/http_transport/src/briareus_http_transport /app/src/briareus_http_transport
COPY shared/mcp_client/src/briareus_mcp_client /app/src/briareus_mcp_client
COPY shared/policies/browser/src/briareus_browser_policy /app/src/briareus_browser_policy
COPY shared/policies/github/src/briareus_github_policy /app/src/briareus_github_policy
COPY shared/policies/gitlab/src/briareus_gitlab_policy /app/src/briareus_gitlab_policy
COPY shared/policies/mcp/src/briareus_mcp_policy /app/src/briareus_mcp_policy
COPY shared/policies/terminal/src/briareus_terminal_policy /app/src/briareus_terminal_policy
COPY shared/python/environment-models/src/briareus_environment_models /app/src/briareus_environment_models
COPY shared/python/secret-files/src/briareus_secret_files /app/src/briareus_secret_files
COPY shared/server/workspace-mount/src/briareus_server_mount /app/src/briareus_server_mount
COPY shared/service_runtime/src/briareus_service_runtime /app/src/briareus_service_runtime
COPY shared/telemetry/src/briareus_telemetry /app/src/briareus_telemetry
COPY shared/websocket_transport/src/briareus_websocket_transport /app/src/briareus_websocket_transport
COPY shared/workspace/src/briareus_workspace /app/src/briareus_workspace
# END BRIAREUS SOURCE PACKAGES
ENV ASGI_APP=control_panel_api.runtime:app
