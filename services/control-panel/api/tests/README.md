# Briareus API validation

Run affected modules from the repository root:

```sh
python tests/run_briareus_contracts.py test_briareus_postgres test_briareus_panel_tokens test_briareus_api_routes test_briareus_api_state
```

Service-local behavior belongs here. Cross-service proxy and WebSocket authority contracts live in `tests/integration/contracts`. The test authority generates an isolated RSA key and supplies external JWKS in memory; no local user session database or production identity provider is involved.

The separate `integration/postgres_migrations.py` entrypoint verifies the fresh schema and encrypted account preservation against disposable PostgreSQL.
