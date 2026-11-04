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

The Dockerfile caches the OS toolchain before installing the owned Python lock.
Durable jobs live in the terminal home volume. Existing independent Files and
Terminal processes must be stopped before a replacement Server can claim their
local volumes; the local launcher guards this explicitly.
