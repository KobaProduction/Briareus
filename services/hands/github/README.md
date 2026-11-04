# Briareus V1 Github

Independent Github MCP hand. Accounts and authority come from the private Control Panel API; this service does not access the panel database directly.

Deploy this owner with `docker-compose.yaml` or the generated
`docker-compose.coolify.yaml`. Use the common environment Destination/network.

The Dockerfile installs this directory's frozen dependency lock and copies its
owned source plus explicitly consumed shared capability packages. The
Dockerfile-specific ignore file excludes all other repository content.
