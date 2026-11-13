# Briareus V1 / Serena

Semantic code navigation and refactoring over Server workspace folders. Register project_id and folder through MCP or SERENA_PROJECTS; each project receives its own stdio process and private Serena state. Process count and idle closure are configurable. No per-project container or network port is created.

The service uses the node private network, standard telemetry and the same external OIDC authorization as other hands.

At most two projects have live child sessions by default
(`SERENA_MAX_PROCESSES=2`); each idle session closes after five minutes
(`SERENA_IDLE_SECONDS=300`). The sweep runs every 15 seconds
(`SERENA_REAP_INTERVAL_SECONDS=15`). An active tool call is never evicted;
a new request will evict the least recently used idle session if the process
limit has been reached. Existing project registrations and code files persist.
Failures closing one project are logged and do not disable the next sweep.

The container runs with `init: true` to reap exited orphaned descendants,
and has a configurable `SERENA_MEMORY_LIMIT` (3 GiB default). This bounds
memory but does not guarantee LSP memory fits; review OOM events before
increasing concurrency. Docker memory limits count child language servers.

Language runtimes belong to Server's shared `<SERVER_MOUNT_PATH>/toolchains`.
Each Serena child prepends `toolchains/bin` from that mount to its PATH, using
the same Node.js, Bun and Go entry points as Server. Install and update those
toolchains through Server; they are not bundled again in the Serena image.
Python for Serena itself remains in its frozen environment. The image provides
a named Unix account for UID 1000 and the system libraries needed by shared Node.

A monorepo must select its languages and workspace folders in
`.serena/project.yml`; automatic initial setup may select only Python. Exclude
dependency directories and nested worktrees from indexing. Restart only that
project's process after changing its language-server configuration. Project
state and language-server processes remain isolated by project_id.

## Operator-owned tools

Agents use runtime UID 1000. Only an operator's separate root terminal in the
Server container installs or updates shared tools. Do not expose a root shell
through MCP. The workspace root must be root-owned with a sticky bit, and the
toolchain tree must be root-owned and not writable by agents. The sticky bit
prevents agents from renaming the protected toolchain directory through its
otherwise writable parent; project directories remain writable.

Serena requires the operator's native `toolchains/serena/serena_config.yml`
before starting a project. It copies that configuration into each private
Serena home, where Serena can maintain its own project state. Native
`ls_base_cmd` settings point to installed language servers and bypass Serena's
automatic package installers. Missing provisioning returns an operator-action
error. `GOTOOLCHAIN=local` also prevents automatic Go toolchain downloads.

The following installation example uses the existing shared Node.js, Bun and
Go runtimes and authorizes only the existing WayLane project. Change the exact
project path when provisioning another project; do not trust a wildcard root.
Run this block in **Coolify → Server application → Terminal as root**, not in
an agent's MCP terminal. Bun installs the JavaScript language servers; npm is
not invoked. The version pins match the Serena version in this image.

```sh
set -eu
test "$(id -u)" -eq 0
server_mount="${SERVER_MOUNT_PATH:-/workspace}"
toolchain_dir="$server_mount/toolchains"
serena_project="$server_mount/projects/waylane/repository"
test -d "$serena_project"
export PATH="$toolchain_dir/bin:$PATH"
command -v node
command -v bun
command -v go
install -d -m 0755 "$toolchain_dir/serena" "$toolchain_dir/bin"
cd "$toolchain_dir/serena"
bun add --exact --ignore-scripts pyright@1.1.403 typescript@5.9.3 typescript-language-server@5.1.3
GOBIN="$toolchain_dir/bin" go install golang.org/x/tools/gopls@v0.24.0
cat > "$toolchain_dir/serena/serena_config.yml" <<EOF
projects: []
trusted_project_path_patterns:
  - "$serena_project"
ls_specific_settings:
  python:
    ls_base_cmd: ["$toolchain_dir/serena/node_modules/.bin/pyright-langserver", "--stdio"]
  typescript:
    ls_base_cmd: ["$toolchain_dir/serena/node_modules/.bin/typescript-language-server", "--stdio"]
  go:
    ls_base_cmd: ["$toolchain_dir/bin/gopls"]
EOF
chown root:root "$server_mount"
chmod 1777 "$server_mount"
chown -R root:root "$toolchain_dir"
chmod -R a+rX,go-w "$toolchain_dir"
```

After changing these tools or this configuration, stop only the affected Serena
project through `stop_project`; its next call starts a fresh process. New tool
requests go to the operator. Do not work around the protected directory by
changing its permissions or installing a second runtime in a project folder.
