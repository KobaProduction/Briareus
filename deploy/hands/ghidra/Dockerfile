ARG BRI_RUNTIME_BASE=bri-v1-runtime-base:local
FROM ${BRI_RUNTIME_BASE}
COPY src/common/__init__.py /app/src/common/__init__.py
COPY src/common/account_contracts.py /app/src/common/account_contracts.py
COPY src/common/asgi.py /app/src/common/asgi.py
COPY src/common/audit_payloads.py /app/src/common/audit_payloads.py
COPY src/common/cache.py /app/src/common/cache.py
COPY src/common/control_panel_client.py /app/src/common/control_panel_client.py
COPY src/common/http_transport.py /app/src/common/http_transport.py
COPY src/common/models.py /app/src/common/models.py
COPY src/common/oauth_session_contracts.py /app/src/common/oauth_session_contracts.py
COPY src/common/observability.py /app/src/common/observability.py
COPY src/common/runtime_common.py /app/src/common/runtime_common.py
COPY src/common/runtime_policy_contracts.py /app/src/common/runtime_policy_contracts.py
COPY src/common/settings.py /app/src/common/settings.py
COPY src/common/tool_observability.py /app/src/common/tool_observability.py
COPY src/modules/__init__.py /app/src/modules/__init__.py
COPY src/modules/ghidra/__init__.py /app/src/modules/ghidra/__init__.py
COPY src/modules/ghidra/runtime.py /app/src/modules/ghidra/runtime.py
ENV ASGI_APP=modules.ghidra.runtime:app
