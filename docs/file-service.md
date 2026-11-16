# V1 workspace file contract — Server Hand

**Owner:** [Server Hand](hands/server.md), deployed at the public MCP path `/server/mcp`. There is **no separate Files MCP** and no independent Curl MCP. A standard `curl` executable is available as a terminal utility when required.

## Shared workspace and paths

The configured `SERVER_MOUNT_PATH` defaults to `/workspace`. Server file operations, authorized GitHub/GitLab worktrees, Playwright downloads and Control Panel API file administration share this persistent volume. Paths are validated under this mount. Traversal and symlink escapes must be rejected.

A canonical Git repository belongs in `/workspace/projects/<repository-name>`. Parallel worktrees are inside the checkout's ignored `.worktrees/` rather than new independent project folders; see [workspaces and Git](operations/git-and-worktrees.md). File operations are not an independent Git workflow authority.

## File transfer

Server provides path-based listing, bounded reads, text writes, binary chunks and attachment ingress. Ingress writes to temporary storage and publishes only after validation of size, destination and optional checksum. A rejected private/non-public attachment URL remains blocked by SSRF validation even when its rejected request is logged below server-error severity.

Playwright downloads are stored in the shared workspace (typically `browser/downloads`). Ghidra native projects remain under the Ghidra engine's private storage boundary; importing/exporting analysis files requires an explicit transfer rather than direct project database mounting.

## Process boundary

Terminal commands and durable jobs share the filesystem but are **not** chroot-isolated solely by their workspace ID. They run under the unprivileged Server application and its explicit mounted resources. Job log retention and workspace directory lifecycle are separate.

See [Server source](../services/hands/server/README.md), [Server tests](../services/hands/server/tests/README.md), [database and recovery](operations/database-and-recovery.md).
