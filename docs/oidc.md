# External OpenID Connect providers

Gateway is the sole server-side OIDC authority in a V1 node. It validates
access tokens, publishes browser configuration and MCP protected-resource
metadata, and prepares the node role at startup. Control Panel API asks Gateway
to verify bearer tokens instead of constructing an independent provider client.
Hands and API have no OIDC environment inputs.

The external identity provider remains the token issuer. The browser uses
Authorization Code + PKCE S256, and separately registered MCP clients own
their OAuth redirects and renewal. Gateway does not become a local issuer or
a generic token-exchange proxy.

## Gateway configuration

| Variable | Meaning |
| --- | --- |
| `OIDC_ISSUER_URL` | Exact issuer including realm path, HTTPS in production |
| `OIDC_AUDIENCE` | Resource audience, distinct from the browser client |
| `OIDC_BROWSER_CLIENT_ID` | Existing public browser registration, no secret |
| `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | Independent confidential resource registration, required only for introspection |
| `OIDC_TOKEN_VERIFICATION` | JWT (default) or RFC 7662 introspection |
| `OIDC_JWT_ALGORITHMS` | Asymmetric allowlist, default RS256 |
| `OIDC_ROLES_CLAIM_PATH` | JSON list of literal claim path segments, default ["roles"] |
| `OIDC_ROLES_FORMAT` | list (default) or organization_grants |
| `OIDC_ROLES_ORGANIZATION_ID` | Required for organization-bound grants |
| `BRIAREUS_NODE_ID` | Required node identity and provider role |
| `OIDC_PROVISIONING_TOKEN` | Separate protected ZITADEL role-provisioning credential |

Only Gateway consumes these deployment inputs. A non-secret shared issuer
may be referenced from Team Shared Variables. Keep protected credentials in
the narrow authorized scope. The provisioning credential is not a resource
client secret. Scopes are derived by the application; no OIDC_SCOPES input
or single-option provisioning-provider selector is required.

## Private verification contract

Control Panel API uses the existing private network DNS `gateway:8000` and
`BRIAREUS_SERVICE_TOKEN`. It obtains node identity and public origin from
`GET /internal/identity/v1/metadata` before initializing its runtime. It
submits the caller's access token to `POST /internal/identity/v1/verify`;
Gateway returns only a bounded verified principal, not raw provider claims
or credentials. Internal routes require the private Host and service bearer.
The private network is a trusted deployment boundary; this HTTP contract is
not mTLS. Do not expose the internal routes as separate public ingress.

API rejects missing, denied and expired identity and checks the returned node
and role. Authority failures fail closed (503 for HTTP); no local verifier
fallback or caller-supplied principal headers are accepted. Existing API
operation-specific authorization and Origin checks remain in force.
Restart API after changing Gateway's node identity or public origin.

Gateway serves `GET /api/identity/config` on the validated public origin.
The browser callback and post-logout redirect remain `<node-origin>/admin/`.
Register that exact URL and allow the node origin for provider CORS.

## Provider behavior

Discovery verifies the returned issuer and obtains the JWKS URI. The signing
keys are cached, and unknown key IDs trigger a refresh. JWT issuer, audience,
signature, expiry, client identity and node grant are required. ID tokens
are not API access tokens. Opaque tokens require explicit introspection mode.
HTTP issuer endpoints are only supported for local test providers.

For ZITADEL use the existing project ID as audience, the public browser
registration as browser client ID, and the project-qualified role claim
`["urn:zitadel:iam:org:project:<project-id>:roles"]` with
`organization_grants` and the correct organization ID. Gateway derives the
project audience and role scopes from this mapping. Its provisioning adapter
creates the node role only when absent, preserving existing assignments.
Failed provisioning prevents Gateway readiness.

## Client naming and migration

Source and local fixtures now use the Gateway-only configuration above.
Do not change the live node until local validation and rollout authorization.

- Move the existing API public client ID into Gateway's OIDC_BROWSER_CLIENT_ID.
- Preserve the existing confidential resource registration under OIDC_CLIENT_ID
  and OIDC_CLIENT_SECRET when introspection is selected.
- Reference the existing authorized provisioning credential in Gateway only.
  Do not reveal, unlock or rotate protected values to perform a rename.
- Preserve previous resource settings and revision for rollback. Bring up
  Dependencies, then the configured Gateway, then API; verify browser login,
  renewal, node grants and authenticated MCP calls on each node independently.
- Remove obsolete OIDC variables, duplicate public origins and node identity
  from saved API/other resource configuration only after verified cutover.

Git Compose changes do not update saved Coolify variables or prove that a live
credential is available. A protected reference unavailable to the operator
blocks deployment; do not substitute invented values.

Reference: [OIDC discovery](https://openid.net/specs/openid-connect-discovery-1_0.html).
