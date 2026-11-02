ARG BRI_RUNTIME_BASE=bri-v1-runtime-base:local
FROM node:22-bookworm-slim AS devtools
RUN npm install --global --prefix /opt/chrome-devtools-mcp chrome-devtools-mcp@1.10.1
FROM ${BRI_RUNTIME_BASE}
COPY --from=devtools /usr/local/bin/node /usr/local/bin/node
COPY --from=devtools /opt/chrome-devtools-mcp /opt/chrome-devtools-mcp
RUN uv sync --frozen --no-dev --group web --no-install-project
ENV CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS=1 CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS=1 CHROME_DEVTOOLS_MCP_NO_CONFIG_DISCOVERY=1
COPY src/common/__init__.py /app/src/common/__init__.py
COPY src/common/account_contracts.py /app/src/common/account_contracts.py
COPY src/common/asgi.py /app/src/common/asgi.py
COPY src/common/audit_payloads.py /app/src/common/audit_payloads.py
COPY src/common/browser_extensions.py /app/src/common/browser_extensions.py
COPY src/common/browser_profile.py /app/src/common/browser_profile.py
COPY src/common/browser_remote_debug.py /app/src/common/browser_remote_debug.py
COPY src/common/cache.py /app/src/common/cache.py
COPY src/common/control_panel_client.py /app/src/common/control_panel_client.py
COPY src/common/http_transport.py /app/src/common/http_transport.py
COPY src/common/models.py /app/src/common/models.py
COPY src/common/oauth_session_contracts.py /app/src/common/oauth_session_contracts.py
COPY src/common/observability.py /app/src/common/observability.py
COPY src/common/runtime_annotations.py /app/src/common/runtime_annotations.py
COPY src/common/runtime_common.py /app/src/common/runtime_common.py
COPY src/common/runtime_policy_contracts.py /app/src/common/runtime_policy_contracts.py
COPY src/common/settings.py /app/src/common/settings.py
COPY src/common/tool_observability.py /app/src/common/tool_observability.py
COPY src/common/websocket_proxy.py /app/src/common/websocket_proxy.py
COPY src/modules/__init__.py /app/src/modules/__init__.py
COPY src/modules/files/__init__.py /app/src/modules/files/__init__.py
COPY src/modules/files/workspace_store.py /app/src/modules/files/workspace_store.py
COPY src/modules/web/__init__.py /app/src/modules/web/__init__.py
COPY src/modules/web/browser.py /app/src/modules/web/browser.py
COPY src/modules/web/browser_control.py /app/src/modules/web/browser_control.py
COPY src/modules/web/browser_tools.py /app/src/modules/web/browser_tools.py
COPY src/modules/web/curl_tools.py /app/src/modules/web/curl_tools.py
COPY src/modules/web/devtools_proxy.py /app/src/modules/web/devtools_proxy.py
COPY src/modules/web/errors.py /app/src/modules/web/errors.py
COPY src/modules/web/executor.py /app/src/modules/web/executor.py
COPY src/modules/web/external_browser_proxy.py /app/src/modules/web/external_browser_proxy.py
COPY src/modules/web/models.py /app/src/modules/web/models.py
COPY src/modules/web/operations.py /app/src/modules/web/operations.py
COPY src/modules/web/operator.py /app/src/modules/web/operator.py
COPY src/modules/web/presets.py /app/src/modules/web/presets.py
COPY src/modules/web/request.py /app/src/modules/web/request.py
COPY src/modules/web/response.py /app/src/modules/web/response.py
COPY src/modules/web/runtime.py /app/src/modules/web/runtime.py
COPY src/modules/web/tools.py /app/src/modules/web/tools.py
ENV ASGI_APP=modules.web.runtime:app
RUN mkdir -p /tmp/bri-browser-transfers && chown 1000:1000 /tmp/bri-browser-transfers
