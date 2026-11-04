# Briareus V1 Control Panel API

Panel API, account configuration and encrypted integration credentials. PostgreSQL schema is managed by packaged Alembic revisions.

Human authentication belongs to external ZITADEL. The panel uses its public SPA client for Authorization Code with PKCE; this API validates project/organization-bound access JWTs using cached external JWKS. There is no local OAuth issuer, user session database, callback or cookie authentication.

`GET /admin/api/identity/config` publishes only public OIDC settings. Protected panel requests send an access token in `Authorization: Bearer`. Browser WebSockets offer `briareus.v1` and `bearer.<access_token>`; the server echoes only `briareus.v1`. Active sockets close at token expiry. Machine-only internal routes use `BRIAREUS_SERVICE_TOKEN`.

Deploy this owner with `docker-compose.yaml` or the generated `docker-compose.coolify.yaml` on the common deployment environment network. The Dockerfile installs its frozen dependency lock and copies owned source plus explicitly consumed shared packages.
