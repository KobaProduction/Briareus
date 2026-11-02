# Official radareorg/radare2 6.2.4 release, published 2026-10-05.
# Asset digest is provided by the upstream GitHub release API. Keep both pinned.
FROM debian:bookworm-slim AS radare2-build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential pkg-config ca-certificates wget xz-utils \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN wget --https-only --secure-protocol=TLSv1_2 --timeout=120 --tries=3 \
      -O radare2.tar.xz https://github.com/radareorg/radare2/releases/download/6.2.4/radare2-6.2.4.tar.xz \
    && echo 'd88a27bdc4da2a5faa4b4223e0e92e6d6d8906dd46b98ea91475d851d703986d  radare2.tar.xz' | sha256sum -c - \
    && tar -xJf radare2.tar.xz \
    && cd radare2-6.2.4 && ./configure --prefix=/usr/local \
    && make -j2 && make install DESTDIR=/radare-install

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy \
    LD_LIBRARY_PATH=/usr/local/lib PYTHONPATH=/app/src
WORKDIR /app
COPY hands/radare2/pyproject.toml hands/radare2/uv.lock hands/radare2/.python-version /app/
RUN uv sync --frozen --no-dev --no-install-project && useradd -u 1000 -m -d /home/hand hand
COPY --from=radare2-build /radare-install/usr/local/ /usr/local/
RUN ldconfig
COPY hands/radare2/src/ /app/src/
COPY shared/hand_runtime/ /app/src/hand_runtime/
COPY shared/node_protocol/ /app/src/node_protocol/
COPY shared/service_runtime/__init__.py shared/service_runtime/_isolated_supervisor_state.py /app/src/service_runtime/
WORKDIR /app/src
USER 1000:1000
EXPOSE 8000
CMD ["/app/.venv/bin/python", "-m", "radare2_hand.node_server"]
