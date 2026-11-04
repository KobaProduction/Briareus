# Briareus V1 Control Panel Api

Panel API, accounts, encrypted credentials, human identity and the hosted MCP OAuth facade. PostgreSQL schema is managed by packaged Alembic revisions.

Deploy this owner with `docker-compose.yaml` or the generated
`docker-compose.coolify.yaml`. Use the common environment Destination/network.

The Dockerfile installs this directory's frozen dependency lock and copies its
owned source plus explicitly consumed shared capability packages. The
Dockerfile-specific ignore file excludes all other repository content.
