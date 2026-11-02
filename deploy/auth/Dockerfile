ARG BRI_RUNTIME_BASE=bri-v1-runtime-base:local
FROM ${BRI_RUNTIME_BASE}
COPY src/auth_service/__init__.py /app/src/auth_service/__init__.py
COPY src/auth_service/api.py /app/src/auth_service/api.py
COPY src/auth_service/identity.py /app/src/auth_service/identity.py
COPY src/auth_service/oauth_routes.py /app/src/auth_service/oauth_routes.py
COPY src/auth_service/provider.py /app/src/auth_service/provider.py
COPY src/auth_service/runtime.py /app/src/auth_service/runtime.py
COPY src/auth_service/token_status.py /app/src/auth_service/token_status.py
COPY src/common/__init__.py /app/src/common/__init__.py
COPY src/common/account_contracts.py /app/src/common/account_contracts.py
COPY src/common/asgi.py /app/src/common/asgi.py
COPY src/common/cache.py /app/src/common/cache.py
COPY src/common/control_panel_client.py /app/src/common/control_panel_client.py
COPY src/common/http_transport.py /app/src/common/http_transport.py
COPY src/common/identity_provider.py /app/src/common/identity_provider.py
COPY src/common/identity_settings.py /app/src/common/identity_settings.py
COPY src/common/mcp_surfaces.py /app/src/common/mcp_surfaces.py
COPY src/common/models.py /app/src/common/models.py
COPY src/common/oauth_session_contracts.py /app/src/common/oauth_session_contracts.py
COPY src/common/observability.py /app/src/common/observability.py
COPY src/common/runtime_policy_contracts.py /app/src/common/runtime_policy_contracts.py
COPY src/common/settings.py /app/src/common/settings.py
ENV ASGI_APP=auth_service.runtime:app
