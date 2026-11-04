# Briareus V1 Analysis

Independent Analysis MCP hand. Accounts and authority come from the private Control Panel API; this service does not access the panel database directly.

The private Ghidra adapter connects to the existing external MCP deployment.
Set required `GHIDRA_DIRECT_UPLOAD_URL` to that deployment's artifact upload endpoint;
the adapter separately requires `GHIDRA_MCP_URL`. Dependencies does not start Ghidra.

Deploy this owner with `docker-compose.yaml` or the generated
`docker-compose.coolify.yaml`. Use the common environment Destination/network.

The Dockerfile installs this directory's frozen dependency lock and copies its
owned source plus explicitly consumed shared capability packages. The
Dockerfile-specific ignore file excludes all other repository content.
