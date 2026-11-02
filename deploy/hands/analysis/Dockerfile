ARG BRI_RUNTIME_BASE=bri-v1-runtime-base:local
FROM ${BRI_RUNTIME_BASE}
COPY src/common/__init__.py /app/src/common/__init__.py
COPY src/common/account_contracts.py /app/src/common/account_contracts.py
COPY src/common/asgi.py /app/src/common/asgi.py
COPY src/common/audit_payloads.py /app/src/common/audit_payloads.py
COPY src/common/cache.py /app/src/common/cache.py
COPY src/common/control_panel_client.py /app/src/common/control_panel_client.py
COPY src/common/http_transport.py /app/src/common/http_transport.py
COPY src/common/mcp_client_pool.py /app/src/common/mcp_client_pool.py
COPY src/common/models.py /app/src/common/models.py
COPY src/common/oauth_session_contracts.py /app/src/common/oauth_session_contracts.py
COPY src/common/observability.py /app/src/common/observability.py
COPY src/common/public_tool_names.py /app/src/common/public_tool_names.py
COPY src/common/runtime_common.py /app/src/common/runtime_common.py
COPY src/common/runtime_policy_contracts.py /app/src/common/runtime_policy_contracts.py
COPY src/common/settings.py /app/src/common/settings.py
COPY src/common/tool_observability.py /app/src/common/tool_observability.py
COPY src/modules/__init__.py /app/src/modules/__init__.py
COPY src/modules/analysis/__init__.py /app/src/modules/analysis/__init__.py
COPY src/modules/analysis/provider.py /app/src/modules/analysis/provider.py
COPY src/modules/analysis/result.py /app/src/modules/analysis/result.py
COPY src/modules/analysis/runtime.py /app/src/modules/analysis/runtime.py
COPY src/modules/analysis/terminology.py /app/src/modules/analysis/terminology.py
COPY src/modules/analysis/workspace_transfer.py /app/src/modules/analysis/workspace_transfer.py
COPY src/modules/files/__init__.py /app/src/modules/files/__init__.py
COPY src/modules/files/workspace_store.py /app/src/modules/files/workspace_store.py
ENV ASGI_APP=modules.analysis.runtime:app
