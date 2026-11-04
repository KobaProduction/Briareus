# Briareus service validation

Run from the repository root:

```sh
python tests/run_briareus_contracts.py test_briareus_postgres test_briareus_panel_identity test_briareus_identity_provider test_briareus_mcp_refresh test_briareus_mcp_revocation
```

Service-local behavior belongs in this directory. Cross-service authority, telemetry and deployment contracts are owned by `tests/integration/contracts`; test helpers are in `tests/support`. The runner resolves each service and shared module from its independent source root.
