# Shared packages, discovery and dependency boundaries

The `shared/` tree is a **library tree**, not a fourth runtime subsystem or a separate backend. Services import only the explicit packages they consume. Each image copies these whole owned packages and each owner Watch Path set includes only its direct/transitive shared dependencies.

## Service catalog and discovery

- `shared/services/catalog` defines known provider identity, group and MCP path metadata.
- `shared/services/discovery` is embedded in **Control Panel API and Gateway**; it is not a discovery container.
- MCP Hands advertise bounded, environment-scoped leases in the existing Valkey.
- Private readiness/identity metadata and node environment must agree before a provider is treated as connected.
- The UI distinguishes an available Hand from a known-but-unavailable source catalog item.
- This availability mechanism does **not** replace OIDC validation, node-role checks or provider authorization.

## Reuse boundaries

Common transport, caching, telemetry, typed JSON/accounts and HTTP/MCP contracts belong to focused shared packages. Account persistence, provider secrets and caller audit remain owned by Control Panel API, not by a generic shared database module. A Hand never imports another Hand's source implementation or opens Control Panel persistence directly.

Runtime variables and special policies belong to the capability that uses them; no omnibus `common` package or root-level runtime that makes independent owners rebuild together. A high-level group name such as `shared/contracts` is a **category**, not permission to Watch/COPY all children.

## Verification

Source imports, build-context generation and Watch Path catalog can be checked with `scripts/briareus_catalog.py --check` and `scripts/briareus_dockerfiles.py --check`. They cannot prove the **saved Coolify** Watch Path configuration, live Valkey leases, actual TLS/OIDC authorization or the provider's tool behavior.

See [runtime](runtime.md), [service owners](../services/README.md), [Hands](../hands/README.md), and [build/Watch Paths](../operations/build-and-watch-paths.md).
