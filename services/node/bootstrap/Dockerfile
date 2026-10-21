FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends util-linux ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY entrypoint.sh host-bootstrap.sh static-tooling.sh /opt/briareus/
ENTRYPOINT ["/bin/sh", "/opt/briareus/entrypoint.sh"]
