# Deploying Briareus V1 on Coolify

**Source branch:** `v1`. **Deployment model:** four independent core applications plus whichever of the **11 optional Hands** are selected for this node. These are **15 possible catalog resources**, not one Docker Compose application. The catalog is [`deploy/services.json`](../../deploy/services.json); each resource owns its `docker-compose.yaml` and generated `docker-compose.coolify.yaml`.

## Topology and isolation

One V1 node contains Control Panel UI, Control Panel API, Gateway and Dependencies (PostgreSQL/Valkey/Chromium). Hands are independently deployed and share the selected node's private Coolify Destination/network. External OIDC and native Ghidra MCP are managed outside these resources. Two V1 nodes have separate public origins, `BRIAREUS_NODE_ID` roles, Destinations, databases, workspaces, browser profiles and volumes.

Gateway is the only public receiver. It proxies `/admin/*`, `/api/*` and each independently connected MCP path. Missing optional Hands do not block the core; an identity-provider outage and a Hand outage are different operational failures.

Do not reuse a Legacy MCP Bridge resource, deleted branch or persistent volume as V1 infrastructure. Do not restart Dependencies when changing only Playwright or the panel. Actual deployment triggers follow each application's saved Coolify Watch Paths, not merely the repository's generated values.

## Build and configuration procedure

1. Confirm the target node/environment, source commit, existing data/volumes and approved deployment scope.
2. Set the node's explicit public origins, `BRIAREUS_NODE_ID`, identity-provider configuration and private service credential. See [configuration](configuration.md).
3. Use the service-owned Compose file and the generated Coolify entrypoint in each service directory. Ensure all selected resources join the same predefined private network/Destination.
4. Generate or check the deployment catalog, restricted Docker contexts and Coolify entrypoints:

```sh
python scripts/briareus_catalog.py --check
python scripts/briareus_dockerfiles.py --check
uv run --frozen --no-env-file --group quality python scripts/briareus_coolify.py --check
```

5. Verify in Coolify the saved parser variables, mount/volume identities, resource paths, Watch Paths, route and secret references. A generated manifest does not update saved Coolify settings.
6. Validate the affected code and schema, deploy **only** selected resources, then verify live revision/health and authenticated consumer calls.

Owner source: [Core services](../services/README.md), [Hands](../hands/README.md). Template: [`deploy/templates/mcp-service.yaml`](../../deploy/templates/mcp-service.yaml). For optional standalone local development and the ZITADEL fixture, see [`deploy/README.md`](../../deploy/README.md) and [database/recovery](database-and-recovery.md).

## Persistence and acceptance

The workspace, Chromium profile and transient transfer storage are distinct external volumes where required; product database/cache volumes remain with Dependencies. Never point a new node at another node's physical volumes. Application rollback is not a database downgrade. Always preserve encrypted records and keys across migrations.

Source checks, green builds and container health are necessary but **not sufficient** for OAuth browser login, MCP refresh/authorization, Playwright-CDP interaction, account resolution, PostgreSQL data or Ghidra tool acceptance. See [test/acceptance levels](testing.md).

## Scope

This document describes V1 and must not be used as V2's autonomous Node deployment contract. V2 has independent requirements and branch-specific configuration.
