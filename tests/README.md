# Briareus validation

Focused tests live beside their owning service under `services/<owner>/tests`.
Cross-service contracts live in `tests/integration/contracts`, isolated external
identity fixtures in `tests/fixtures`, and reusable harnesses in `tests/support`.

Run one suite from the repository root:

```sh
python tests/run_briareus_contracts.py test_briareus_panel_identity
```

At the final review boundary, run the aggregate once:

```sh
uv run --frozen --no-env-file --group quality python scripts/quality_gate.py --all --tests
```

The default contract runner uses the local frozen development environment
without Docker on every platform. A separate frozen Linux contract image remains
available with `python tests/run_briareus_contracts.py --docker` when Docker
conformance is intentionally requested. A Docker run uses a read-only source
snapshot excluding ignored state, credentials and frontend node_modules.
Product deployments do not depend on either test mode.

## Database acceptance

SQLite is the default local test engine; PostgreSQL is opt-in. Neither requires
Docker to run the normal suite:

```sh
uv run --frozen --no-env-file --group quality python scripts/quality_gate.py --all --tests
BRIAREUS_TEST_DATABASE_BACKEND=both BRIAREUS_TEST_POSTGRES_MODE=native \
  uv run --frozen --no-env-file --group quality python scripts/quality_gate.py --all --tests
```

`sqlite`, `postgresql`, and `both` each earn a separate test receipt. Local
commit and push hooks accept the receipt for the selected backend (SQLite by
default). PostgreSQL-specific acceptance is retained in CI with native PostgreSQL
when database components change. A SQLite receipt **does not** claim Postgres
advisory-lock or transaction-rollback coverage. For native/external test-only
PostgreSQL and backend configuration, see `services/control-panel/api/tests/README.md`.
