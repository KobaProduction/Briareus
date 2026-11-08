# Briareus V1 deployment

V1 is a **single-server node**, not the authority for the entire Briareus system.
Each node owns its Gateway, panel, MCP providers, workspace and PostgreSQL data.
`BRIAREUS_NODE_ID` identifies the node independently of its public HTTPS origin
(for example, `tambov` or `morshansk`). API and Gateway use the same required value.
The authenticated bootstrap and Gateway ping expose that configured node identity.

All nodes use the same external OpenID provider. Each node requires its own role.
Register a separate public panel client per node with its exact `/admin/` callback
and logout URI. Bind each node's existing `MCP_PUBLIC_BASE_URL`,
`CONTROL_PANEL_PUBLIC_BASE_URL`, `MCP_ALLOWED_HOSTS` and `MCP_ALLOWED_ORIGINS`
to that node's origin. Do not use wildcard OAuth callbacks or share local data
volumes between nodes.

## Environment-driven node-role preparation

Set `BRIAREUS_NODE_ID` on both Control Panel API and Gateway. This value is also
the required identity-provider role; there is no separate role-name setting or
fallback to a global access grant. Domains and node identity are separate inputs.

Control Panel API prepares the node role during startup, before accepting traffic:
it reuses an existing role or creates a missing one. Concurrent creation is safe.
Existing role metadata and user assignments are preserved. Users receive node access
only when an administrator assigns that node's role in the identity provider.

API alone requires `OIDC_PROVISIONING_PROVIDER=zitadel` and the protected
`OIDC_PROVISIONING_TOKEN`. In Coolify bind the token resource variable to the existing
protected provisioning credential in Shared Variables. Keep the provider, node ID,
issuer and project audience as public Runtime variables, Buildtime=false. Gateway,
UI and MCP hands do not receive the provisioning token. Failed identity setup blocks
API readiness and reports a sanitized startup error.

The provider adapter uses the existing `OIDC_ISSUER_URL` and `OIDC_AUDIENCE` project
identifier. Application token verification remains generic OpenID Connect. This is
an ordinary environment-driven service startup step, not a manual registration CLI.

The Docker network below connects services **within one node**. A common identity
provider does not create a network between servers or schedule tasks across nodes.
Cross-node transport, a node registry and distributed task scheduling are separate
capabilities; the current panel shows only the connected node's state and MCP calls.
When provisioning another server, give it an isolated Destination and storage;
retain the existing Destination and volume names when renaming the current node.

The application has eleven deployment resources with separate update lifecycles:

| Resource | Containers | Ownership |
| --- | ---: | --- |
| Control Panel UI | 1 | Independently built frontend |
| Dependencies | 3 | PostgreSQL, Valkey, persistent Chromium |
| Gateway | 1 | Public HTTP/MCP routing |
| Control Panel API | 1 | Panel backend, PostgreSQL state, external-token verification |
| MCP hands | 7 | Server, GitHub, GitLab, Web, Analysis, Ghidra proxy, Observability |

This is **13 product containers**, grouped by lifecycle rather than one deployment
per container. The existing external Ghidra MCP engine and bridge are managed by
their own deployment; Briareus runs only its private adapter to that MCP.
A panel or provider source update does not restart PostgreSQL, Valkey or Chromium.

Provision V1 as a **new, clean Coolify project/environment** with eleven new
resources on branch `v1`. Keep the working Legacy MCP Bridge and V2 resources,
their configured branches, domains, network, storage and credentials unchanged.
The new V1 receives its own environment Destination, persistent volumes and
protected configuration. This is a parallel installation, not an in-place
upgrade or a data import from Legacy MCP Bridge.

All internal services attach to one application network,
`briareus-v1-${DEPLOYMENT_ENVIRONMENT}-private`. PostgreSQL also owns the `database`
DNS alias; its direct service address is `postgres:5432`. No database, browser CDP
or Ghidra port is published. There is no PgBouncer or additional control plane.

## Identity and database authority

**The production OpenID provider is external.** Set `OIDC_ISSUER_URL`,
`OIDC_AUDIENCE`, the public `OIDC_PANEL_CLIENT_ID` and provider-specific scopes/role
mapping on API/Gateway. Discovery supplies provider endpoints and public keys.
UI uses Code + PKCE; API/Gateway verify JWTs locally. There are no Briareus OAuth
signing/introspection keys, login cookies or user-session storage.
See [OIDC setup and migration](../docs/oidc.md) and [MCP setup](../docs/oauth-chatgpt.md).

`BRIAREUS_SERVICE_TOKEN` is one shared secret for participating internal Briareus
calls. Rotation requires recreating all consumers; changing a Shared Variable
alone does not alter an existing container's environment. It is separate from the
ZITADEL provisioning PAT, database passwords and stored-credential encryption key.
Keep only secrets in Shared Variables. All addresses, public IDs, deployment
labels and other configuration belong to application resources.

The panel uses PostgreSQL through SQLAlchemy and psycopg. Alembic owns the
versioned application schema; the new baseline has no local identity/session
or OAuth authority tables. The API applies revisions before accepting requests.
This is a fresh installation; retain Legacy databases/volumes for later migration.

## Generic and Coolify entrypoints

Each catalog resource has `docker-compose.yaml` and generated
`docker-compose.coolify.yaml`. `deploy/services.json` records exact consumed
source paths, Dockerfiles and Watch Paths. Dependencies owns only third-party infrastructure recipes, versions and configuration.
Its Chromium image contains distro Chromium, Xvfb, nginx and upstream Supervisor.
There is no Briareus Python process or shared module in that resource.

Use `python scripts/briareus_catalog.py` after changing imports and
`python scripts/briareus_coolify.py` after changing generic Compose. The `--check`
option verifies generated Coolify inputs remain synchronized. Generic Compose
works independently; Coolify inputs remove host port bindings and delegate shared
connectivity to the selected Destination's **Connect To Predefined Network**.
All eleven resources must select that same environment Destination. Verify the
actual parser's service DNS aliases, secrets, mounts, required fields, public
routes and saved Watch Paths before rollout. Source validation is not proof of
saved Coolify settings or a live deployment.

Each deployment owns its source and build inputs below `services/`. Control
Panel UI and API are siblings under `services/control-panel`; MCP hands live
under `services/hands/<name>`. Each Python image installs its owner's frozen
manifest and copies whole owned packages plus consumed shared packages. Root
development manifests and dependency-service sources are not application inputs.

Watch Paths contain only the owner directory with `/**` and consumed shared
capability directories with `/**`. No individual filenames, root-wide or
all-shared watches are used. The catalog follows transitive package imports
and rejects cross-service source imports. Workspace storage lives in `shared/workspace`; the canonical mount and project paths
live in `shared/server/workspace-mount`. Provider identity belongs to API.
`shared/python/environment-models`, `environment-parsing` and `secret-files` have
separate purposes. Typed policy clients and their contracts are separate leaf modules.
Watch the consumed leaf with `/**`, never an entire shared category.

Use `python scripts/briareus_catalog.py` to refresh catalog/COPY inputs, then
`python scripts/briareus_dockerfiles.py` to update restricted Docker contexts.
CI checks both without needing a tracked operator handout. Each image is
self-contained, with its own frozen dependencies and no required base publication.

Export the private setup handout into ignored local state:

```powershell
python scripts/briareus_catalog.py --export .local/briareus-v1-coolify/watch-paths.txt
```

Use each owner directory as Coolify Base Directory and
`/docker-compose.coolify.yaml` as Compose Location. Save Watch Paths explicitly
on each new resource; generating a handout does not update platform settings.

Ghidra MCP runs in its existing external deployment. Dependencies starts only
PostgreSQL, Valkey and Chromium. Configure the actual reachable `GHIDRA_MCP_URL`
for the private Ghidra adapter and `GHIDRA_DIRECT_UPLOAD_URL` for Analysis artifact
uploads; both are required deployment inputs. Briareus does not build Ghidra or
create another engine/MCP runtime.

Cross-resource workspace, browser profile and browser-transfer storage are
explicit external volumes in Coolify, so its parser cannot create a separate
resource-prefixed copy for each consumer. Provision the three **new V1** volume
names before deployment:

```text
briareus-v1-${DEPLOYMENT_ENVIRONMENT}-workspace
briareus-v1-${DEPLOYMENT_ENVIRONMENT}-browser
briareus-v1-${DEPLOYMENT_ENVIRONMENT}-browser-transfers
```

Other dependency
volumes belong to their owning resource. Never point this clean V1
installation at Legacy MCP Bridge or V2 volumes.


## Server, browser and infrastructure boundaries

Server is one deployment with one MCP `/server/mcp`. File operations, terminal
commands and durable jobs share `SERVER_MOUNT_PATH` (default `/workspace`).
GitHub/GitLab checkouts use that same root; `projects/<id>/repo` is visible to
commands in project `<id>`. Command cwd/path arguments are validated, but the
shell is not a chroot: its authority is the unprivileged Server container and
its explicitly mounted volumes.

Completed browser files live at `browser/downloads` under that shared mount.
Server can list/read/move them into projects. Chromium and Web consume the same
workspace storage; transient browser transfer files remain separate. Curl is an
installed Server command, with no separate Web curl MCP tools.

Dependencies watches exactly `services/dependencies/**`. It has no application
source owner, Python lock or dependency on `shared`. Web owns browser settings,
profile/extensions and launch-policy translation. It communicates with upstream
Supervisor over the private network and writes runtime launch arguments into the
persistent profile volume. Loading/redeploying Web does not stop or relaunch an
already-running Chromium. Explicit lifecycle and extension actions may do so.
The generic Chromium image uses only its own infrastructure context.

## Operator configuration

`DEPLOYMENT_ENVIRONMENT` is Required with no Compose fallback. Valid application
values are `development`, `staging`, `production`, and `test`. It determines the
network and production volume namespace, and becomes
`deployment.environment.name` in telemetry.

| Input | Owner and behavior |
| --- | --- |
| `SERVER_MOUNT_PATH` | Shared container path for Server/Git/Web/API/Analysis; default `/workspace` |
| `POSTGRES_USERNAME` | Dependencies/API, default `postgres`; maps to upstream `POSTGRES_USER` |
| `POSTGRES_DATABASE` | Dependencies/API, default `briareus`; maps to upstream `POSTGRES_DB` |
| `POSTGRES_PASSWORD` | Required protected credential, no default |
| `VALKEY_USERNAME` | Dependencies/consumers, default `default` |
| `VALKEY_PASSWORD` | Required protected credential; real ACL authentication, no URL-embedded secret |
| `OIDC_ISSUER_URL` | Required external issuer; production HTTPS |
| `OIDC_PANEL_CLIENT_ID` / `OIDC_AUDIENCE` | Registered public panel client / protected API audience |
| Public API/MCP origins | Required deployment origins, not guessed localhost production defaults |
| `OTEL_NAMESPACE` | Project identity; `service.namespace`, default `briareus` |
| `OTEL_ENDPOINT` | Collector endpoint, Required when remote export is configured |
| `OTEL_BEARER_TOKEN` | Protected credential only when that endpoint requires Bearer |
| `OTEL_SERVICE_NAME` | Fixed per instrumented service, owned by source |
| `CONTROL_PANEL_FRONTEND_TELEMETRY_UPSTREAM_URL` | Optional explicit browser telemetry forwarder; disabled when empty |
| `CONTROL_PANEL_FRONTEND_TELEMETRY_BEARER_TOKEN` | Protected runtime credential only for that explicitly configured endpoint |

Valkey creates an ACL file from the supplied credential on startup and rejects
unauthenticated access. API/cache clients pass username/password separately from
the stable internal topology URL. Secret values do not belong in Git, logs,
image layers or copied deployment examples.

Real OTLP SDK delivery has been verified against an isolated local receiver for
logs, traces and metrics, including resource identity and optional Bearer headers.
This does not claim that a production collector is configured or receiving data.

## Local development and schema upgrades

The local launcher uses the existing checkout and deterministic Compose projects
`briareus-v1-development-<catalog-unit>`. Docker Desktop therefore shows Dependencies
as a five-container group, API and UI as independent groups, and each MCP owner
separately. Every group shares the same application network. The launcher accepts
only `development`, because its local overlays intentionally retain one existing
set of physical volumes; use generic Compose for other environments.

`init` creates ignored `.local/briareus-v1` inputs only when absent and preserves all
existing secrets. It adds PostgreSQL/Valkey credentials without rotating them.
The ignored `.local/briareus-development.json` may select an existing state
directory, environment aliases and exact physical volume identities. Local
overrides preserve those volumes and credentials without creating replacement data. Generic production volumes instead derive from
the deployment environment. Existing ignored backups are not application inputs.

For an existing local stack, stop its exact `briareus-v1-local` containers before
starting replacement projects: two owners must never write the same volume.
The launcher refuses a cutover while legacy writers remain active. Do not use
`--remove-orphans`, global cleanup, or delete volumes when changing deployments.

```powershell
python scripts/briareus_local.py init
python scripts/briareus_local.py build dependencies control-panel-api
python scripts/briareus_local.py dependencies
python scripts/briareus_local.py build
python scripts/briareus_local.py up
python scripts/briareus_local.py status
```

The API runs Alembic `upgrade head` against its configured PostgreSQL database
before startup. A fresh database receives the initial revision; subsequent
revisions are applied in order. PostgreSQL serializes concurrent migration
attempts. A failed revision prevents API startup and preserves the previous
transactional schema/data. An existing unversioned PostgreSQL schema may adopt
the initial revision only after its full baseline structure is verified;
incompatible or partial schemas fail closed rather than being stamped blindly.

Schema changes belong in new, immutable revisions under the API's packaged
Alembic directory. Review the revision's upgrade and recovery behavior, validate
it on fresh and existing PostgreSQL states, then build/deploy only the API.
Application model changes do not automatically alter deployed tables.

Create a revision from a writable development checkout using the packaged
configuration and standard Alembic API:

```powershell
uv run --frozen python -c "from alembic import command; from control_panel_api.infrastructure.migrations import migration_config; command.revision(migration_config(), message='describe schema change')"
```

Review and implement the generated revision before deployment. Autogeneration
requires an explicit development PostgreSQL connection passed to
`migration_config(connection)`; do not generate revisions inside a deployed,
immutable application image. The standard revision template is bundled with the
API package and watched alongside its migration source.

For one changed application owner use `build <unit>` then `up <unit>`; this does
not select Dependencies. A changed dependency runtime uses the Dependencies
resource, whose unchanged Compose services retain their containers and data.

## Optional external identity test fixture

`tests/fixtures/zitadel` is a separate, opt-in local test system with four
containers and its own identity network/project. It is outside the Briareus network
and is never included by root/product Compose or a production deployment.
The test network is an ordinary separate bridge: `internal: true` would suppress
the ingress's loopback port publication on Docker Desktop. It never attaches to
the application network.

```powershell
python scripts/briareus_local.py identity-test
python scripts/briareus_local.py identity-bootstrap
```

The test issuer is `http://auth.briareus.localhost:18081`. Its ingress is bound only to
`127.0.0.1:18081`; local-only application overlays use host-gateway resolution,
not Docker network attachment. HTTP issuers exist only in localhost tests. Production uses the external HTTPS
issuer; Briareus does not set authentication cookies. The fixture plus the product totals seventeen local containers,
but only thirteen belong to Briareus. Existing identity state and credentials remain
unchanged across fixture-project migration.

## Acceptance and rollback

Validate affected contracts and composed manifests, then run the full final suite
once after source freeze. Confirm real PostgreSQL query/persistence, API sign-in,
MCP grants/refresh/revocation, Web CDP reconnect and Ghidra consumer calls. Compare
physical volumes, Alembic revision and preserved encrypted records across upgrades.
Never substitute TCP health for database contents or Ghidra MCP callability.

Keep PostgreSQL backups and the existing OAuth/provider volumes and keys before
schema changes. Application rollback must remain compatible with the installed
schema; restoring an old image does not automatically downgrade the database.
Use a reviewed forward correction or an explicitly planned database restore for
an incompatible schema change. Never run concurrent owners against the same
browser/provider volume. Live Coolify and production rollout require their own
parser, persistence, external identity and consumer acceptance; local checks do
not claim those operations happened.
