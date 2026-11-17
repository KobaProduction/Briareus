# Validation and acceptance — V1

Tests answer different questions; do not treat a single green check as production acceptance.

1. **Source/static:** generated catalog/Dockerfile/Compose consistency, Ruff, strict mypy, Python and UI type/build checks.
2. **Local contracts:** service-owner Python tests, cross-service integration and UI behavior; no Docker needed for the default local suite.
3. **Database:** local tests use explicitly selected SQLite by default; PostgreSQL is separately tested (e.g. native PostgreSQL in CI). SQLite does **not** prove PostgreSQL advisory locks, concurrency or production migration safety.
4. **Deployment:** Coolify saved configuration, real network aliases, persistence, secrets, Watch Paths, image revision and health on the target node.
5. **Consumer acceptance:** authenticated MCP calls, OIDC renewal, browser operations, Git/GitLab account permissions and native analysis backend behavior.

For the final source review, use the established quality gate:

```sh
BRIAREUS_TEST_DATABASE_BACKEND=sqlite uv run --frozen --no-env-file --group quality python scripts/quality_gate.py --all --tests
```

See [test README](../../tests/README.md), [API database modes](../../services/control-panel/api/tests/README.md), [source workflows](../../.github/workflows/ci.yaml), and [deployment](deployment.md). Do not claim CI checks or a running container prove browser login or database contents.

**Documentation-only changes** should additionally validate all tracked relative links, owner targets, active terminology and consistency against `deploy/services.json`. Avoid deploying services solely to check a documentation update.


### Parallel Rust MCP pilot

The experimental [SigNoz Rust Hand](../../services/hands/observability/signoz-rust/README.md)
has its own frozen Cargo lock, Rust unit tests and an offline MCP/HTTP
parity harness. Run those checks independently; Python's aggregate
V1 quality gate does not yet verify the Rust SDK or prove runtime cutover.
The Rust pilot remains unregistered and unexposed until authenticated
integration, observability, policy and independent rollback are accepted.
