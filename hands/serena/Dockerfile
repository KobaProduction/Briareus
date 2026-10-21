# Real upstream Serena and its language servers are installed only at image build.
FROM node:22.16.0-bookworm-slim AS language_servers
RUN npm install --global --ignore-scripts --no-audit --no-fund \
    pyright@1.1.403 typescript@5.9.3 typescript-language-server@5.1.3

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git clangd-14 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=language_servers /usr/local/bin/node /usr/local/bin/node
COPY --from=language_servers /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/pyright/langserver.index.js /usr/local/bin/pyright-langserver \
    && ln -s /usr/local/lib/node_modules/typescript-language-server/lib/cli.mjs /usr/local/bin/typescript-language-server
ADD --checksum=sha256:62e5562b464521ccbbb9cc3e85fae3b31ffb0f216bc4e1622466e4923b721998 \
    https://codeload.github.com/oraios/serena/tar.gz/4c4268f9c0adf8743a75e6dda2ef1fa635f34cc3 /tmp/serena.tar.gz
RUN mkdir -p /opt/serena \
    && tar -xzf /tmp/serena.tar.gz --strip-components=1 -C /opt/serena \
    && rm /tmp/serena.tar.gz \
    && uv sync --project /opt/serena --frozen --no-dev \
    && /opt/serena/.venv/bin/python -c "import serena; import importlib.metadata as m; assert m.version('serena-agent') == '2.0.0'"
WORKDIR /app
COPY hands/serena/pyproject.toml hands/serena/uv.lock /app/
RUN uv sync --frozen --no-dev --no-install-project \
    && useradd -u 1000 -m -d /home/hand hand
COPY hands/serena/src/ /app/src/
COPY shared/hand_runtime/ /app/src/hand_runtime/
COPY shared/node_protocol/ /app/src/node_protocol/
COPY shared/runtime_peer/ /app/src/runtime_peer/
ENV UV_OFFLINE=1 UV_PYTHON_DOWNLOADS=never
LABEL org.opencontainers.image.source="https://github.com/oraios/serena" \
      io.briareus.serena.upstream.revision="4c4268f9c0adf8743a75e6dda2ef1fa635f34cc3"
WORKDIR /app/src
USER 1000:1000
CMD ["/app/.venv/bin/python", "-m", "serena_hand.node_server"]
