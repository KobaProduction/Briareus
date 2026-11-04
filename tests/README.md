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

On Windows the runner builds its separate frozen Linux contract image if needed
and mounts a read-only source snapshot. Git-ignored state, credentials, frontend
node_modules and local virtual environments are excluded. On Linux it uses the
frozen development environment. Product deployments do not depend on this image
or the root development dependency manifests.

Real PostgreSQL migration acceptance belongs to the API:

```sh
uv run --frozen --no-env-file python services/control-panel/api/tests/integration/postgres_migrations.py
```
