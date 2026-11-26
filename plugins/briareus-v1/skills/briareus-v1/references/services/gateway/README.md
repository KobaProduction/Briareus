# Briareus V1 Gateway

Public routing, protected resource metadata, private API and MCP transport.

Deploy this owner with `docker-compose.yaml` or the generated
`docker-compose.coolify.yaml`. Use the common environment Destination/network.

Coolify supplies `SERVICE_URL_GATEWAY` from the single
`SERVICE_URL_GATEWAY_8000: /` route. Gateway validates the canonical origin
and derives exact FastMCP Host/Origin policy from that URL; the deprecated
`MCP_ALLOWED_HOSTS`, `MCP_ALLOWED_ORIGINS` and separately set
`MCP_PUBLIC_BASE_URL` are **not** Coolify operator inputs. Standalone Compose
keeps `MCP_PUBLIC_BASE_URL` as a required portable origin.

External identity remains provider-neutral: set `OIDC_ISSUER_URL` to the
approved provider issuer via a Team Shared reference in the Gateway
Coolify resource; do not copy a provider hostname into source defaults.
Gateway owns browser client configuration, token verification and node-role provisioning. API calls the private identity contract with the existing service credential. Existing saved variables need deliberate reconciliation before live cutover. See [OIDC](../../docs/oidc.md).

The Dockerfile installs this directory's frozen dependency lock and copies its
owned source plus explicitly consumed shared capability packages. The
Dockerfile-specific ignore file excludes all other repository content.
