# Native Gateway candidate; launch boundary is chosen by its Compose entrypoint.
FROM rust:1.95.0-slim-bookworm AS build
WORKDIR /src
COPY shared/oidc-verifier/Cargo.toml shared/oidc-verifier/Cargo.toml
COPY shared/oidc-verifier/src/ shared/oidc-verifier/src/
COPY shared/service-discovery/Cargo.toml shared/service-discovery/Cargo.toml
COPY shared/service-discovery/src/ shared/service-discovery/src/
COPY services/gateway-rust/Cargo.toml services/gateway-rust/Cargo.lock services/gateway-rust/
COPY services/gateway-rust/catalog.json services/gateway-rust/catalog.json
COPY services/gateway-rust/src/ services/gateway-rust/src/
ENV CARGO_BUILD_JOBS=2
RUN cargo build --release --locked --manifest-path services/gateway-rust/Cargo.toml

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/services/gateway-rust/target/release/briareus-gateway-rust /usr/local/bin/briareus-gateway
USER 10001:10001
ENV PORT=8000 BIND_HOST=0.0.0.0
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/briareus-gateway"]
