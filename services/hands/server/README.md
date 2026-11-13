# Briareus V1 Server

One service, one `/server/mcp` surface and one `briareus_server` application
package. Internal `files` and `terminal` modules provide file operations,
workspaces, shell execution and persistent jobs. Files and Terminal are no longer
independent deployments or MCP surfaces.

`SERVER_MOUNT_PATH` (default `/workspace`) is shared with GitHub/GitLab checkout,
Web/browser downloads, API file administration and Analysis. Terminal project
cwd is `projects/<id>`; check out a repository into `projects/<id>/repo` to work
on it there. Shell commands run as UID1000 in the container, not in a project chroot.

Finished browser files are in `browser/downloads`. Use file operations or shell
commands to move/process them. Curl and git are installed by the service-owned
`system-packages.txt`; no curl MCP feature exists in Web.

The service runs with Docker `init: true`, so orphaned exited child
processes are reaped, and keeps the configured `SERVER_MEMORY_LIMIT`
(3 GiB by default). Terminal commands and jobs run in separate process
groups. The manager sends TERM/KILL on exit, cancellation or timeout, while
preserving completed job metadata.

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
