# Persistence, browser lifecycle and external engines

## Shared volumes

Several resources use the same explicitly mounted **V1** persistent files; others own private volumes. The node's shared workspace, browser profile and browser-transfer storage have separate purposes:

- Workspace: Server file/terminal jobs and authorized consumers, including Git checkouts and Playwright downloads.
- Browser profile: authenticated Chromium profile/settings; not a generic Files directory.
- Browser-transfer storage: transient data-plane transfer between browser and workspace owners.
- PostgreSQL and Valkey: Dependencies owner; PostgreSQL application state is durable, Valkey is a cache/lease service.
- Native Ghidra projects: **external** engine-owned data, not the Server filesystem.

Do not attach two independent node environments to the same writable physical data volume merely because their names match. New V1 installations require distinct, reviewed external volume names, node network and Destination. Preserve existing volume identities when changing an application's display name.

## Browser resource ownership

Dependencies owns the running Chromium container, Xvfb/Supervisor and memory cgroup. Playwright owns CDP session/click/reconnect behavior and Browser Operator interaction. A Playwright redeploy does not imply Chromium restart. Changing a `CHROMIUM_MEMORY_LIMIT` deployment variable may require container recreation or a separate live cgroup update; verify the actual memory limit and `oom_kill` counter before claiming an effect.

A browser click blocked by an overlay is an actionable caller-state warning; a CDP/Chromium OOM or transport timeout is a real runtime failure. Use source [Playwright settings](../../services/hands/web/playwright/README.md) and [Chromium source](https://github.com/KobaProduction/Briareus/blob/v1/services/dependencies/chromium/README.md).

## Data recovery

Do not delete the browser profile, workspace, production database or encrypted account keys during Git cleanup or an unrelated Hand update. A container/image rollback does not downgrade a schema. See [database and recovery](database-and-recovery.md), [deployment](deployment.md), [Server Hand](../hands/server.md).
