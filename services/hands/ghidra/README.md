# Briareus V1 Ghidra

Briareus-owned adapter to the external Ghidra MCP service configured by required `GHIDRA_MCP_URL`.
This adapter is configurable and maintained with Briareus; the external Ghidra MCP
implementation is built separately from its pinned repository. Accounts and authority come from the private Control Panel API; this service does not access the panel database directly.

Deploy this owner with `docker-compose.yaml` or the generated
`docker-compose.coolify.yaml`. Use the common environment Destination/network.

The Dockerfile installs this directory's frozen dependency lock and copies its
owned source plus explicitly consumed shared capability packages. The
Dockerfile-specific ignore file excludes all other repository content.
