ARG BRI_RUNTIME_BASE=bri-v1-runtime-base:local
FROM ${BRI_RUNTIME_BASE}
COPY src/common/__init__.py /app/src/common/__init__.py
COPY src/common/account_contracts.py /app/src/common/account_contracts.py
COPY src/common/asgi.py /app/src/common/asgi.py
COPY src/common/cache.py /app/src/common/cache.py
COPY src/common/control_panel_client.py /app/src/common/control_panel_client.py
COPY src/common/gateway_settings.py /app/src/common/gateway_settings.py
COPY src/common/http_transport.py /app/src/common/http_transport.py
COPY src/common/identity_settings.py /app/src/common/identity_settings.py
COPY src/common/mcp_surfaces.py /app/src/common/mcp_surfaces.py
COPY src/common/models.py /app/src/common/models.py
COPY src/common/oauth_session_contracts.py /app/src/common/oauth_session_contracts.py
COPY src/common/observability.py /app/src/common/observability.py
COPY src/common/runtime_annotations.py /app/src/common/runtime_annotations.py
COPY src/common/runtime_policy_contracts.py /app/src/common/runtime_policy_contracts.py
COPY src/common/settings.py /app/src/common/settings.py
COPY src/common/websocket_proxy.py /app/src/common/websocket_proxy.py
COPY src/gateway/__init__.py /app/src/gateway/__init__.py
COPY src/gateway/application/__init__.py /app/src/gateway/application/__init__.py
COPY src/gateway/application/token_status.py /app/src/gateway/application/token_status.py
COPY src/gateway/auth_client.py /app/src/gateway/auth_client.py
COPY src/gateway/backend_router.py /app/src/gateway/backend_router.py
COPY src/gateway/backend_sessions.py /app/src/gateway/backend_sessions.py
COPY src/gateway/models.py /app/src/gateway/models.py
COPY src/gateway/reverse_proxy.py /app/src/gateway/reverse_proxy.py
COPY src/gateway/server.py /app/src/gateway/server.py
COPY src/gateway/token_status.py /app/src/gateway/token_status.py
ENV ASGI_APP=gateway.server:app
