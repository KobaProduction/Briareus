# BRI V1 deployment units

V1 keeps the existing MCP contracts and public paths. Each unit has its own
`docker-compose.yaml`, Coolify entrypoint `docker-compose.coolify.yaml`, source
image, and change scope. `services.json` is the machine-readable service and
watch-path catalog. Paths are repository-relative.

| Unit | Compose directory | Source owner |
| --- | --- | --- |
| Dependencies | `deploy/dependencies` | Valkey image/configuration only |
| Identity dependencies | `deploy/dependencies/zitadel` | PostgreSQL, ZITADEL API/Login, private identity ingress |
| Gateway | `deploy/gateway` | `src/gateway`, its exact common imports |
| MCP OAuth adapter | `deploy/auth` | `src/auth_service`, its exact common imports |
| Control Panel API | `deploy/control-panel-api` | `src/control_panel_api`, its common/files imports |
| Control Panel UI | `deploy/control-panel-ui` | `control-panel-ui` |
| Persistent Chromium | `deploy/chromium` | `src/browser_runtime`, WebSocket framing helper |
| Optional native Ghidra | `deploy/dependencies/ghidra-native` | pinned unchanged vendor Java engine and MCP bridge |
| MCP providers | `deploy/hands/<provider>` | `src/modules/<provider>`, actual transitive imports |

Provider names are `github`, `gitlab`, `files`, `web`, `terminal`, `analysis`,
`ghidra`, and `observability`. Analysis consumes the Ghidra proxy. A native Ghidra
MCP server is a separately supplied external backend; a healthy proxy container
does not establish that this upstream is available.

The optional `native-ghidra` profile retains the existing pinned native build
adapter from the V2 local deployment without importing Node, Access, or their
contracts. Its upstream checkout must be clean at the revision in
`deploy/dependencies/ghidra-native/source.json`. The Ghidra archive is verified
against the SHA-256 published by the official NSA release. The vendor source is
not modified, vendored into this branch, or included in unrelated app builds.

For the local optional backend, prepare the pinned checkout, then run:

```powershell
python scripts/bri_local.py init
python scripts/bri_local.py build native-ghidra
python scripts/bri_local.py up native-ghidra
```

`init` records `BRI_GHIDRA_SOURCE_DIR` and `BRI_SOURCE_DIR` in the ignored runtime
environment; neither is a secret. The build verifies the actual resolved Compose
context against the pinned clean Git checkout. Engine, native MCP bridge, data,
projects, and artifacts have their own new local resources and no host ports.
Normal `build`/`up` excludes this optional profile. Its absence requires a
separately verified `GHIDRA_MCP_URL`; proxy TCP health is never native readiness.

The root `Dockerfile` builds `bri-v1-runtime-base:local`: pinned third-party Python
dependencies and common system tools, without application source. Per-unit
Dockerfiles copy only their owner source and the import closure recorded in the
catalog. UI uses its own frozen Bun dependency environment. Web additionally
installs Playwright and the pinned Chrome DevTools MCP client; Chromium and Xvfb
live only in the Chromium image.

The local image name is a fresh-local default, not a remotely published image.
For a separately approved Coolify rollout, first build the dependency image from
the same `Dockerfile`/`pyproject.toml`/`uv.lock`, publish it through the approved
registry, and set `BRI_RUNTIME_BASE` to that available immutable tag or digest.
Each Python unit forwards this explicit Compose build argument to its Dockerfile.
Registry credentials belong in the deployment platform, not source or browser
configuration. This foundation neither publishes a registry image nor changes
live Coolify settings. A remote unit is not deployment-ready until that exact
base image and saved build/Compose/watch settings have been verified there.

A dependency lock change affects the dependency image and its consuming images.
An API or UI source change does not redeploy dependencies, browser, or unrelated
providers. Use each catalog entry's explicit `watch_paths`, not `src/**` or
`src/common/**`. The shared files listed for a unit are real direct/transitive
imports. In particular, Files workspace helpers are also consumed by Web,
Analysis, and Control Panel API.

## Isolated local stack

Use the main checkout; the launcher does not create another worktree.

```powershell
python scripts/bri_local.py init
python scripts/bri_local.py dependencies
python scripts/bri_local.py identity-bootstrap
python scripts/bri_catalog.py
python scripts/bri_local.py config
python scripts/bri_local.py build
python scripts/bri_local.py up
python scripts/bri_local.py status
```

`init` creates fresh ignored `.local/bri-v1` credentials only when absent.
`identity-bootstrap` provisions a real local ZITADEL project, explicit human
subject, and OIDC client. It keeps initial login credentials in
`.local/bri-v1/secrets/initial-admin-password`, never in logs or source. Subsequent
runs preserve credentials and provider state. Application startup requires the
resulting real client ID and subject allowlist; there is no guessed issuer,
first-visitor administrator, or GitHub-authentication fallback.

The stack uses Compose project `bri-v1-local`, fresh `bri-v1-local-*` volumes,
and external networks `bri-v1-private` and `bri-v1-browser-private`. Existing
Briareus, OpenFlare, and Waylane resources are outside its scope. Valkey and
ZITADEL's PostgreSQL have durable volumes. Control Panel keeps its own SQLite
adapter and volume; this foundation does not migrate it to PostgreSQL.

Only Gateway `127.0.0.1:18080` and identity ingress `127.0.0.1:18081` are published.
The canonical local identity issuer is `http://auth.bri.localhost:18081`.
The identity ingress has that Docker DNS alias and listens internally on the same
port. The browser resolves the localhost domain to loopback. Production requires
a real configured HTTPS issuer; local HTTP is an explicit development setting.

For one changed unit, build/start only that catalog unit, for example:

```powershell
python scripts/bri_local.py build control-panel-api
python scripts/bri_local.py up control-panel-api
```

The build command ensures the cached third-party base exists, then builds only
selected units. Independent Compose files contain no app-to-app `depends_on`:
unavailable upstreams remain unavailable rather than restarting another unit.

## Chromium ownership

Chromium owns its profile, Xvfb, process lifecycle, and private CDP listener.
Web connects over CDP and uses its existing operator/developer/page policies.
Only Web and Chromium join the browser network. CDP and the lifecycle adapter
have no host ports. Explicit lifecycle commands require a backend credential;
they are forwarded only after existing Web authorization.

Ordinary Web reconnect/redeployment disconnects Playwright without closing the
persistent remote browser or tabs. Explicit restart preserves the profile;
explicit hard stop kills the browser process group until an explicit restart.
Page-specific operator locks are persisted by Chromium target ID so reconnecting
Web does not automatically unlock a retained tab.

## Existing deployments and state

These files describe the fresh local foundation. They do not authorize a live
cutover, create Coolify resources, or migrate/reset existing volumes.

Legacy Control Panel storage is the physical `management` volume mounted at
`/management`, with `management.sqlite3`. A future approved cutover must map that
same physical volume and preserve its filename explicitly, for example
`CONTROL_PANEL_DATABASE_PATH=/var/lib/bri/control-panel/management.sqlite3` when
changing only the mount target. The fresh-local default filename is not a
migration. Preserve existing encryption/session/signing keys and OAuth storage;
renaming configuration keys does not authorize rotating their values.

ZITADEL reauthentication replaces GitHub-derived human identity. Existing
provider account credentials remain separate from human sign-in. Retired GitHub
identity claims grant no access under the new issuer/subject checks.

Coolify entrypoints and saved Base Directory/Compose/Watch settings must be
verified independently during a separately approved rollout. No live deployment
settings are changed by this source split. CI path/configuration compatibility
also requires its separately authorized scope; this document does not claim CI
acceptance.
