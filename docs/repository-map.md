# Briareus V1 repository map

See [the ownership layout](../README.md#repository-layout).

- `services/control-panel/ui`: frontend, assets, Bun dependencies, Dockerfile and Compose.
- `services/control-panel/api`: API, hosted OAuth, identity, SQLAlchemy and Alembic revisions.
- `services/gateway`: public routing and private API/provider clients.
- `services/dependencies`: third-party PostgreSQL/Valkey/Chromium/Ghidra lifecycle, without Briareus source.
- `services/hands/server`: one file/terminal application package and deployment.
- `services/hands/<name>`: independent MCP hand, source, dependencies and build inputs.
- `shared/<capability>/src/<package>`: reusable modules with explicit transitive consumers.
- Service `tests` directories: tests owned by that service.
- `tests/integration`: cross-service contracts and real PostgreSQL acceptance.
- `tests/support`: reusable fixtures; `tests/fixtures`: opt-in external identity fixture.
- `scripts`: developer checks, manifest generators and local launcher.
- `deploy/services.json`: ordered deployment catalog, frontend first.

The root Python manifest/lock and Dockerfile serve development/testing. Product
images use service-owned manifests. Root Compose is optional; each deployment
has its own independent Compose entrypoint. Watch patterns use directories with
`/**` only. Private operator handouts are exported into ignored `.local`.

Shared categories contain semantic leaf modules. Consumer watches select each
leaf directory, such as `shared/policies/browser/**`; category-wide contracts
or configuration watches are forbidden.
