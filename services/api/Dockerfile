FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy
WORKDIR /app
COPY services/api/pyproject.toml services/api/uv.lock /app/
RUN --mount=type=cache,target=/root/.cache/uv,sharing=shared uv sync --frozen --no-dev --no-install-project
RUN useradd -u 1000 -m -d /home/control-panel control-panel
COPY services/api/src/ /app/src/
COPY shared/runtime_peer/ /app/src/runtime_peer/
COPY shared/node_protocol/ /app/src/node_protocol/
COPY shared/service_runtime/__init__.py shared/service_runtime/_uuid_field_validation.py shared/service_runtime/_reference_bindings.py shared/service_runtime/_async_http_lifecycle.py shared/service_runtime/_field_serialization.py shared/service_runtime/_http_errors.py /app/src/service_runtime/
COPY shared/owner_protocol/__init__.py /app/src/owner_protocol/__init__.py
COPY shared/owner_protocol/domain/__init__.py shared/owner_protocol/domain/authority.py /app/src/owner_protocol/domain/
USER 1000:1000
WORKDIR /app/src
EXPOSE 8000
CMD ["/app/.venv/bin/python", "-m", "uvicorn", "control_panel_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
