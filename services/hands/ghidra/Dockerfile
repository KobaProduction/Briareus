# BEGIN BRIAREUS PYTHON RUNTIME
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS python-runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy PYTHONPATH=/app/src
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates gosu netcat-openbsd && rm -rf /var/lib/apt/lists/*
COPY services/hands/ghidra/pyproject.toml services/hands/ghidra/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
RUN mkdir -p /var/lib/briareus/control-panel /workspace /browser/profile /home/agent /home/briareus && chown -R 1000:1000 /var/lib/briareus /workspace /browser /home/agent /home/briareus
ENV HOME=/home/briareus
EXPOSE 8000
ENTRYPOINT ["/usr/sbin/gosu", "1000:1000"]
CMD ["/app/.venv/bin/python", "-m", "briareus_service_runtime.asgi"]
# END BRIAREUS PYTHON RUNTIME
# BEGIN BRIAREUS SOURCE PACKAGES
COPY services/hands/ghidra/src/briareus_ghidra /app/src/briareus_ghidra
COPY shared/cache/src/briareus_cache /app/src/briareus_cache
COPY shared/contracts/accounts/src/briareus_account_contracts /app/src/briareus_account_contracts
COPY shared/contracts/http-surface/src/briareus_http_surface /app/src/briareus_http_surface
COPY shared/contracts/invocation-events/src/briareus_invocation_events /app/src/briareus_invocation_events
COPY shared/contracts/json-values/src/briareus_json_values /app/src/briareus_json_values
COPY shared/control_panel_client/src/briareus_control_panel_client /app/src/briareus_control_panel_client
COPY shared/hand_runtime/src/briareus_hand_runtime /app/src/briareus_hand_runtime
COPY shared/http_transport/src/briareus_http_transport /app/src/briareus_http_transport
COPY shared/python/environment-models/src/briareus_environment_models /app/src/briareus_environment_models
COPY shared/python/environment-parsing/src/briareus_environment_parsing /app/src/briareus_environment_parsing
COPY shared/service_runtime/src/briareus_service_runtime /app/src/briareus_service_runtime
COPY shared/services/catalog/src/briareus_service_catalog /app/src/briareus_service_catalog
COPY shared/services/discovery/src/briareus_service_discovery /app/src/briareus_service_discovery
COPY shared/telemetry/src/briareus_telemetry /app/src/briareus_telemetry
# END BRIAREUS SOURCE PACKAGES
ENV ASGI_APP=briareus_ghidra.runtime:app
