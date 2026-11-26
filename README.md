# Briareus V1

Briareus V1 is a **multi-service MCP platform**: one Gateway and Control Panel, independent MCP Hands, and stable PostgreSQL/Valkey/Chromium dependencies. Human authentication uses an external OpenID Connect provider; Briareus does not run a local user identity issuer.

The active version is maintained on Git branch `v1`; **`v2` is a separate, future architecture** with autonomous Nodes, different ownership and its own documentation. Do not equate V1's deployed node with V2's Node model.

## Documentation by owner

| Start here | What it describes |
| --- | --- |
| [Agent instructions](AGENTS.md) | Required reading/routing and safe source changes |
| [Documentation index](docs/README.md) | All current owner domains |
| [Core architecture](docs/core/README.md) | V1 boundaries, security and service ownership |
| [Core services](docs/services/README.md) | Gateway, Control Panel UI/API and Dependencies |
| [MCP Hands](docs/hands/README.md) | Server, Playwright, GitHub/GitLab, analyzers, SigNoz/Coolify, Serena |
| [Operations](docs/operations/README.md) | Coolify, configuration, persistence, tests and Git/worktrees |
| [Architecture decisions](docs/decisions/README.md) | Accepted/superseded choices |
| [History](docs/history/README.md) | Non-operative legacy design records |

## What exists in V1

The authoritative [deployment catalog](deploy/services.json) currently declares **15 independent resources**: 4 core services and 11 **optional** MCP Hands. Not every Hand is deployed on every node; a resource's source presence does not confirm live availability.

- **Control Panel UI** — web frontend at `/admin/*`.
- **Control Panel API** — node administration, encrypted account credentials, persistence and realtime at `/api/*`.
- **Gateway** — public HTTPS bearer authorization, protected-resource metadata and independent MCP routes.
- **Dependencies** — private PostgreSQL, Valkey and persistent Chromium.
- **Hands** — separately deployed file/terminal/jobs, Playwright, provider source control, program analysis, SigNoz observation and authorized Coolify operations and optional semantic tools.

There is **no independent Management container, local OAuth issuer, legacy root MCP Bridge, separate Files/Terminal/Curl MCP, or aggregate Web/Observability MCP**. System `curl` can still be used as a Server terminal command. Serena is optional and currently intentionally stopped.

## Source layout

```text
services/
  control-panel/{ui,api}/       # separately deployed Control Panel applications
  gateway/                      # public routing and bearer resource boundary
  dependencies/                 # PostgreSQL / Valkey / Chromium
  hands/                        # 11 independently built optional MCP services
shared/                         # focused consumer-imported capabilities
deploy/services.json            # authoritative application/Watch Path catalog
deploy/templates/               # shared MCP Compose inputs
docs/{core,services,hands,operations,history}/
tests/                           # cross-owner contracts and fixtures
```

Services own manifests/locks/build inputs; shared packages serve explicit consumers. Each application has its own Compose entrypoint; changing a Hand does not imply restarting Dependencies. See [repository map](docs/repository-map.md) and [deployment](docs/operations/deployment.md).

## Identity, data and validation

OIDC provider tokens are verified by Gateway alone; API delegates verification through a private authenticated contract (JWT locally by default, explicit introspection mode available). The required node role is `BRIAREUS_NODE_ID`; browser UI uses Code + PKCE. Control Panel persistence defaults to **PostgreSQL/Alembic**, with SQLite supported only when explicitly selected for local/testing. Shared workspace files belong to the Server data plane; Ghidra native projects remain isolated.

Start with [OIDC configuration](docs/oidc.md), [MCP OAuth](docs/oauth-chatgpt.md), [database/recovery](docs/operations/database-and-recovery.md) and [validation](docs/operations/testing.md). Source state, CI, Coolify saved configuration and authenticated consumer acceptance are separate evidence.
