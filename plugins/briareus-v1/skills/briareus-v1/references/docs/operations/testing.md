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

See [test README](https://github.com/KobaProduction/Briareus/blob/v1/tests/README.md), [API database modes](https://github.com/KobaProduction/Briareus/blob/v1/services/control-panel/api/tests/README.md), [source workflows](https://github.com/KobaProduction/Briareus/blob/v1/.github/workflows/ci.yaml), and [deployment](deployment.md). Do not claim CI checks or a running container prove browser login or database contents.

### Native Gateway and API runtime acceptance

Run the actual Python Gateway and API startup entrypoints as isolated local
processes (no Docker, no live secrets, no persistent production data):

```sh
.venv/bin/python tests/run_briareus_contracts.py test_briareus_gateway_runtime
cargo build --locked --manifest-path services/gateway-rust/Cargo.toml
BRIAREUS_TEST_GATEWAY_BINARY="$PWD/services/gateway-rust/target/debug/briareus-gateway-rust" .venv/bin/python tests/run_briareus_contracts.py test_briareus_gateway_runtime
```

Both runs use a synthetic OIDC authority, temporary SQLite database and an
unavailable Valkey endpoint to exercise degraded operation. Only the private
Gateway transport address is overridden in the API test composition root.
The same tests check JWT and introspection, HTTP/WebSocket access, fail-closed
behavior during Gateway downtime, reconnect without API restart and SQLite
reopen. Rust uses local shadow mode; separate private-preview tests exercise
role provisioning. This does not establish real provider login/renewal,
production networking, PostgreSQL or live cutover acceptance.

**Documentation-only changes** should additionally validate all tracked relative links, owner targets, active terminology and consistency against `deploy/services.json`. Avoid deploying services solely to check a documentation update.


### Active SigNoz Rust cutover and remaining acceptance

The [SigNoz Rust Hand](../../services/hands/observability/signoz-rust/README.md)
has a frozen Cargo lock, Rust unit tests, offline Python/MCP parity and
adversarial network/discovery tests. Its private resource now serves the
existing Gateway route on `tambov`, while the previously built Python image remains stopped as a temporary rollback asset.
The V1 quality gate and Rust-specific CI are distinct acceptance receipts.
Live authenticated SigNoz tools, Control Panel audit HTTP acceptance,
Valkey lease and memory limits were checked at cutover; OTel collector
delivery, saved Coolify configuration migration, OIDC renewal and full rollback
drill are not yet proved.
