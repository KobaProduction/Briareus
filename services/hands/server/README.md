# Briareus V1 Server

One service, one `/server/mcp` surface and one `briareus_server` application
package. Internal `files` and `terminal` modules provide file operations,
workspaces, shell execution and persistent jobs. Files and Terminal are no longer
independent deployments or MCP surfaces.

`SERVER_MOUNT_PATH` (default `/workspace`) is shared with GitHub/GitLab checkout,
Web/browser downloads, API file administration and Analysis. The canonical Git
checkout is `projects/<repository-name>`; agents must reuse that directory and
create linked worktrees inside its ignored `.worktrees/` for parallel development.
A Server workspace ID identifies a command/job context, not a required nested
`projects/<id>/repo` clone. Follow
[the V1 Git/worktree policy](../../../docs/operations/git-and-worktrees.md).
The current workspace API accepts arbitrary valid workspace IDs and does not
enforce Git-repository naming; the checkout provider needs its own path guard.
Shell commands run as UID1000 in the container, not in a project chroot.

Finished browser files are in `browser/downloads`. Use file operations or shell
commands to move/process them. The curl and git command-line utilities are installed by the service-owned
`system-packages.txt`; no curl MCP feature exists in Web.

The service runs with Docker `init: true`, so orphaned exited child
processes are reaped, and keeps the configured `SERVER_MEMORY_LIMIT`
(3 GiB by default). Terminal commands and jobs run in separate process
groups. The manager sends TERM/KILL to each owned process group on shell exit,
cancellation or timeout, including when the shell leader has exited but a child
ignores TERM. Completed job metadata is preserved. Docker's init process reaps
adopted zombies promptly; it is not a timer-based SIGKILL, because zombies have
already exited and cannot be killed. Processes belonging to a live non-reaping
parent need that parent to call wait(). Do not kill unrelated sessions or active
jobs after an arbitrary 300 seconds.

Automatic retention cleanup runs during the Server app lifespan. By default
it scans on startup and every hour and removes only finished job records and
logs older than seven days, up to 1000 per pass. It **never** deletes workspace
directories or running/cancelling jobs. Operators can set
`TERMINAL_AUTO_CLEANUP_ENABLED`, `TERMINAL_CLEANUP_INTERVAL_SECONDS`,
`TERMINAL_JOB_RETENTION_HOURS` and `TERMINAL_CLEANUP_BATCH_SIZE`. The
manual `job_cleanup` tool remains available for previews and exact control.

The Dockerfile caches the OS toolchain before installing the owned Python lock.
Durable jobs live in the terminal home volume. Existing independent Files and
Terminal processes must be stopped before a replacement Server can claim their
local volumes; the local launcher guards this explicitly.

## MCP workflow guidance

The Server Hand embeds `skills/server-project-workflow/SKILL.md` within its
source package. It publishes that file as an MCP `skill://` resource, the
experimental `io.modelcontextprotocol/skills` extension, a
`project_workflow` MCP prompt and the `read_project_workflow` read-only tool.
This gives tool-only clients an explicit way to retrieve the same guidance.

The workflow checks existing canonical Git checkouts before invoking
`workspace_create` or terminal commands. It is **agent guidance**, not an
enforcement policy: the current terminal can still run arbitrary authorized
shell commands.

The Hand advertises `git-<12 hex characters>` in its MCP server version when
Coolify passes `SOURCE_COMMIT` to the container. Outside such deployments, it
uses a deterministic `src-<hash>` of the packaged Hand source and skill files.
The Python `pyproject.toml` package version is independent of the MCP revision.
