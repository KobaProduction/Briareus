# Briareus V1 deployment

The application has twelve deployment resources with separate update lifecycles:

| Resource | Containers | Ownership |
| --- | ---: | --- |
| Dependencies | 5 | PostgreSQL, Valkey, persistent Chromium, Ghidra Java engine and MCP bridge |
| Gateway | 1 | Public HTTP/MCP routing |
| Control Panel API | 1 | Panel backend, PostgreSQL state, human sessions and MCP OAuth facade |
| Control Panel UI | 1 | Independently built frontend |
| MCP providers | 8 | GitHub, GitLab, Files, Web, Terminal, Analysis, Ghidra proxy, Observability |

This is **16 product containers**, grouped by lifecycle rather than one deployment
per container. The two Ghidra processes are the pinned repository's engine and MCP
transport, inside Dependencies. They are not a second external analysis product.
A panel or provider source update does not restart PostgreSQL, Valkey or Chromium.

Provision V1 as a **new, clean Coolify project/environment** with twelve new
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

**Production ZITADEL is external.** Supply its HTTPS issuer, registered client,
client secret and explicit subject allowlist. It is not in the product Compose
entrypoint, catalog or network. The API hosts OAuth and panel routes in the same
ASGI process; there is no standalone Auth deployment. Gateway sends both routes
to that API. Existing OAuth state/signing keys remain durable and unchanged.

The panel uses PostgreSQL through SQLAlchemy and psycopg. Alembic owns the
versioned schema, including human identity transactions and sessions. The API
applies pending revisions before accepting requests; repositories never create
tables. PostgreSQL owns its persistent volume; provider runtimes use the API,
not direct database access. There is no SQLite runtime or transfer utility.

## Generic and Coolify entrypoints

Each catalog resource has `docker-compose.yaml` and generated
`docker-compose.coolify.yaml`. `deploy/services.json` records exact consumed
source paths, Dockerfiles and Watch Paths. Dependencies owns all manifests,
Chromium source/imports and pinned Ghidra build inputs under its directory.

Use `python scripts/bri_catalog.py` after changing imports and
`python scripts/bri_coolify.py` after changing generic Compose. The `--check`
option verifies generated Coolify inputs remain synchronized. Generic Compose
works independently; Coolify inputs remove host port bindings and delegate shared
connectivity to the selected Destination's **Connect To Predefined Network**.
All twelve resources must select that same environment Destination. Verify the
actual parser's service DNS aliases, secrets, mounts, required fields, public
routes and saved Watch Paths before rollout. Source validation is not proof of
saved Coolify settings or a live deployment.

For each Coolify resource use its catalog directory as Base Directory and
`/docker-compose.coolify.yaml` as Compose Location. The generated
[`watch-paths.txt`](watch-paths.txt) contains all twelve branch/Base Directory/
Compose Location mappings and a pasteable **one-pattern-per-line** Watch Paths
block for each resource. Save those paths explicitly on the corresponding new
resource; a webhook or generated file does not update saved Coolify settings.

Watch Paths contain the resource's `deploy/<owner>/**`, its own source directories,
and the exact shared source files it actually imports. The API owns
`src/control_panel_api/**` and `src/auth_service/**`. UI owns
`control-panel-ui/**`; Dependencies owns `src/browser_runtime/**`. New files under
those owners trigger the correct resource without adding each filename manually.
Shared `src/common` and cross-provider helpers stay explicit; no `src/**` or
`src/common/**` watch scope is used. Folder watches include their owning README
and local overlays intentionally, so a documentation-only edit can redeploy that
one resource. The shared Python recipe generator is an explicit input for Python
resource watches. Publish its regenerated Dockerfiles together with recipe edits.
Compose/catalog generator edits are reflected by their generated resource inputs;
CI verifies those outputs before acceptance.

| Example change | Selected resource |
| --- | --- |
| UI view, UI package or Bun lock | Control Panel UI |
| API endpoint, Alembic revision or OAuth facade | Control Panel API |
| Web MCP action | Web |
| Persistent browser process/lifecycle | Dependencies |
| `common/identity_provider.py` | Control Panel API |
| `common/browser_extensions.py` | Dependencies and Web |
| Root Python recipe, dependency lock or build context filter | Consuming Python resources |

CI runs `python scripts/bri_catalog.py --check` on every checkout. It compares
the actual import graph with image COPY inputs, catalog watches and the pasteable
export. A new owner file or shared import cannot silently remain absent from its
image or Watch Paths. Regenerate with `python scripts/bri_catalog.py` after
source/import changes; it preserves each source image's build stages.

The root Dockerfile is the frozen third-party Python recipe. Each application
Dockerfile includes its synchronized `runtime-dependencies` build stage and copies
only the owner's source/import closure. Remote Git-backed builds do not require
a pre-existing local base image or a registry publication; BuildKit can reuse the
identical dependency layers across independent resources. The local launcher may
use its prebuilt base as an explicit optimization.
Ghidra fetches the unchanged public repository revision pinned in
`dependencies/ghidra-native/source.json` during its image build. Its official
archive hash is verified. No server-local source checkout is a build prerequisite.

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
and OAuth volumes belong to their owning resource. Never point this clean V1
installation at Legacy MCP Bridge or V2 volumes.

## Operator configuration

`DEPLOYMENT_ENVIRONMENT` is Required with no Compose fallback. Valid application
values are `development`, `staging`, `production`, and `test`. It determines the
network and production volume namespace, and becomes
`deployment.environment.name` in telemetry.

| Input | Owner and behavior |
| --- | --- |
| `POSTGRES_USERNAME` | Dependencies/API, default `postgres`; maps to upstream `POSTGRES_USER` |
| `POSTGRES_DATABASE` | Dependencies/API, default `bri`; maps to upstream `POSTGRES_DB` |
| `POSTGRES_PASSWORD` | Required protected credential, no default |
| `VALKEY_USERNAME` | Dependencies/consumers, default `default` |
| `VALKEY_PASSWORD` | Required protected credential; real ACL authentication, no URL-embedded secret |
| `ZITADEL_ISSUER_URL` | Required external issuer; production HTTPS |
| `ZITADEL_CLIENT_ID` / subject allowlist | Required real registered client and identities |
| Public API/MCP origins | Required deployment origins, not guessed localhost production defaults |
| `OTEL_NAMESPACE` | Project identity; `service.namespace`, default `briareus` |
| `OTEL_ENDPOINT` | Collector endpoint, Required when remote export is configured |
| `OTEL_BEARER_TOKEN` | Protected credential only when that endpoint requires Bearer |
| `OTEL_SERVICE_NAME` | Fixed per instrumented service, owned by source |

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

`init` creates ignored `.local/bri-v1` inputs only when absent and preserves all
existing secrets. It adds PostgreSQL/Valkey credentials without rotating them.
Local overrides retain the existing physical `bri-v1-local-*` workspace, browser,
Valkey, Ghidra and OAuth volumes. Generic production volumes instead derive from
the deployment environment. Existing ignored backups are not application inputs.

For an existing local stack, stop its exact `bri-v1-local` containers before
starting replacement projects: two owners must never write the same volume.
The launcher refuses a cutover while legacy writers remain active. Do not use
`--remove-orphans`, global cleanup, or delete volumes when changing deployments.

```powershell
python scripts/bri_local.py init
python scripts/bri_local.py build dependencies control-panel-api
python scripts/bri_local.py dependencies
python scripts/bri_local.py build
python scripts/bri_local.py up
python scripts/bri_local.py status
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
python scripts/bri_local.py identity-test
python scripts/bri_local.py identity-bootstrap
```

The test issuer is `http://auth.bri.localhost:18081`. Its ingress is bound only to
`127.0.0.1:18081`; local-only application overlays use host-gateway resolution,
not Docker network attachment. HTTP issuer and non-HTTPS session cookie settings
exist only in local overrides. Production uses the external HTTPS issuer and
secure cookies. The fixture plus the product totals twenty local containers,
but only sixteen belong to Briareus. Existing identity state and credentials remain
unchanged across fixture-project migration.

## Acceptance and rollback

Validate affected contracts and composed manifests, then run the full final suite
once after source freeze. Confirm real PostgreSQL query/persistence, API sign-in,
MCP grants/refresh/revocation, Web CDP reconnect and Ghidra consumer calls. Compare
physical volumes, Alembic revision and preserved encrypted records across upgrades.
Never substitute TCP health for database contents or native Ghidra callability.

Keep PostgreSQL backups and the existing OAuth/provider volumes and keys before
schema changes. Application rollback must remain compatible with the installed
schema; restoring an old image does not automatically downgrade the database.
Use a reviewed forward correction or an explicitly planned database restore for
an incompatible schema change. Never run concurrent owners against the same
browser/provider volume. Live Coolify and production rollout require their own
parser, persistence, external identity and consumer acceptance; local checks do
not claim those operations happened.
