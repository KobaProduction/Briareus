# Persistence, browser lifecycle and external engines

## Shared volumes

Several resources use the same explicitly mounted **V1** persistent files; others own private volumes. The node's shared workspace, browser profile and browser-transfer storage have separate purposes:

- Workspace: projects, Git checkouts, Playwright downloads, toolchains and Server terminal home in one physical named volume. Server mounts the existing `home/agent` subpath at `/home/agent`; no independent terminal-home volume remains in the desired model.
- Browser profile: authenticated Chromium profile/settings; not a generic Files directory.
- Browser-transfer storage: transient data-plane transfer between browser and workspace owners.
- PostgreSQL and Valkey: Dependencies owner; PostgreSQL application state is durable, Valkey is a cache/lease service.
- Native Ghidra projects: **external** engine-owned data, not the Server filesystem.

Do not attach two independent node environments to the same writable physical data volume merely because their names match. New V1 installations require distinct, reviewed external volume names, node network and Destination. Preserve existing volume identities when changing an application's display name.

## Server home provisioning and migration

The shared workspace root must be root-owned with mode `1777`; create its
`home` parent root-owned mode `0700` and `home/agent` owned by UID/GID 1000
mode `0700` before the Server container is created. The Docker Engine
`volume.subpath` mount requires a pre-existing directory. It preserves the
terminal's absolute home paths without exposing it through the ordinary
UID 1000 workspace mount. Trusted host administrators still control the volume.

For a fresh local development environment, the local launcher provisions the
subpath using a one-shot, network-disabled container from the Server image.
For standalone or Coolify installations, the operator provisions it in the
actual node's already-created workspace volume. Do not initialize a blank home
if a previous terminal-home volume contains state. For migration, verify the
old and new volume identities and free space, stop Server and any other old
home writers, copy the old home tree into the new subpath preserving metadata
and hardlinks, and compare the copy before starting the new Server. Retain the
old volume for rollback until authenticated terminal/job acceptance; remove it
only after checking there are no remaining consumers and recovery is available.
Verify the persisted Coolify Compose has two mounts of the same workspace
volume, including `volume.subpath: home/agent` at `/home/agent`.

## Browser resource ownership

Dependencies owns the running Chromium container, Xvfb/Supervisor and memory cgroup. Playwright owns CDP session/click/reconnect behavior and Browser Operator interaction. A Playwright redeploy does not imply Chromium restart. Changing a `CHROMIUM_MEMORY_LIMIT` deployment variable may require container recreation or a separate live cgroup update; verify the actual memory limit and `oom_kill` counter before claiming an effect.

A browser click blocked by an overlay is an actionable caller-state warning; a CDP/Chromium OOM or transport timeout is a real runtime failure. Use source [Playwright settings](../../services/hands/web/playwright/README.md) and [Chromium source](../../services/dependencies/chromium/README.md).

## Data recovery

Do not delete the browser profile, workspace, production database or encrypted account keys during Git cleanup or an unrelated Hand update. A container/image rollback does not downgrade a schema. See [database and recovery](database-and-recovery.md), [deployment](deployment.md), [Server Hand](../hands/server.md).
