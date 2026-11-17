# Server Hand — files, terminal and jobs

**Catalog:** `server`. **Source:** [`services/hands/server`](../../services/hands/server/README.md). **Public MCP:** `/server/mcp`.

One service owns file operations, workspaces, shell commands, persistent asynchronous jobs and interactive PTYs. There is **no separate Files MCP or Terminal MCP**. Git and other system utilities, including `curl`, may be invoked as terminal commands; none is a separate Curl MCP service.

## Shared filesystem

`SERVER_MOUNT_PATH` defaults to `/workspace`. Server, permitted GitHub/GitLab checkouts, Playwright downloads and API file administration use that shared volume; the Ghidra native project store remains isolated. File operations use bounded paths, atomic/validated uploads and guards against traversal and symlink escape. See [Files contract](../file-service.md).

Under `/workspace/projects`, create **one canonical repository folder per Git repository**, named after the repository (`briareus`, not `briareus-<task>`). Concurrent agents use `git worktree add` inside that repository's ignored `.worktrees/`. Terminal workspace IDs name Server's persistent command contexts; **they are not a mandate to create another Git clone or `projects/<id>/repo`**. Follow the [V1 Git/worktree policy](../operations/git-and-worktrees.md) before creating or reusing repository directories. Current Server workspace operations do not themselves guarantee canonical Git names.

## Process and retention model

Short operations use bounded exec; long-lived work uses jobs, optionally PTY-backed. Jobs have cursor-addressed output and explicit cancel/wait/delete. The Server image runs non-root (UID 1000) under Docker init, with configured memory budget. Process-group cleanup terminates owned children, not other sessions. Finished-job records/logs have bounded automatic retention (enabled by default) and manual `job_cleanup` preview; **workspace directories are not automatically deleted**. Operators must distinguish job-log cleanup from project/worktree cleanup.

See the [source README](../../services/hands/server/README.md) for settings and specifics, [tests](../../services/hands/server/tests/README.md) for focused checks, and [deployment](../operations/deployment.md).
