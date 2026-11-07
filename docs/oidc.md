# External OpenID Connect providers

Briareus is an OIDC public client and an OAuth resource server. It does not host an
identity provider. The panel uses `oidc-client-ts`, Authorization Code + PKCE S256,
discovery and RP-initiated logout. API and MCP Gateway validate signed JWT access
tokens locally. Opaque access tokens/introspection are not supported.

## Application configuration

Keep all these public values on application resources, outside Shared Variables.
API and Gateway must use the same verification and role policy.

| Variable | Meaning |
| --- | --- |
| `OIDC_ISSUER_URL` | Exact issuer, including realm path when applicable; HTTPS in production |
| `OIDC_AUDIENCE` | API audience present in access tokens; separate from the public panel client ID |
| `OIDC_PANEL_CLIENT_ID` | Registered public browser client; API resource only; no client secret |
| `OIDC_SCOPES` | CSV scopes; defaults to `openid,profile,email,offline_access` |
| `OIDC_JWT_ALGORITHMS` | Explicit CSV asymmetric allowlist, default `RS256` |
| `OIDC_ROLES_CLAIM_PATH` | JSON array of literal claim path segments, default `["roles"]` |
| `OIDC_ROLES_FORMAT` | `list` (default) or `organization_grants` |
| `OIDC_ROLES_ORGANIZATION_ID` | Required only for organization-bound grants |
| `OIDC_REQUIRED_ROLE` | Required application role, default `access` |

The browser callback and post-logout redirect are `<node-origin>/admin/`. Register
that exact URL and allow the node origin for provider CORS. Enable Code + PKCE
and refresh tokens for public clients if requesting `offline_access`. MCP clients
are registered separately with their own callback URL, API audience and scopes.
An ID token addressed only to the browser client cannot authorize the API.

Discovery uses `<issuer>/.well-known/openid-configuration`, verifies the returned
issuer exactly and obtains `jwks_uri`. Metadata and JWKS cache for five minutes;
unknown signing key IDs trigger a JWKS refresh. HTTPS verification remains on.
HTTP endpoints are accepted only for localhost test providers. Missing/invalid
roles, audience, issuer, expiry or signature fail closed. Tokens require `sub`,
`exp`, `iat`, and `client_id` or `azp`; optional `nbf` is enforced when present.
Role changes/revocation affect existing JWTs at expiry; configure short lifetimes.

## ZITADEL

Configure these values explicitly, substituting the actual IDs:

```dotenv
OIDC_ISSUER_URL=https://identity.example
OIDC_AUDIENCE=<project-id>
OIDC_PANEL_CLIENT_ID=<public-client-id>
OIDC_SCOPES=openid,profile,email,offline_access,urn:zitadel:iam:org:projects:roles,urn:zitadel:iam:org:project:id:<project-id>:aud
OIDC_ROLES_CLAIM_PATH=["urn:zitadel:iam:org:project:<project-id>:roles"]
OIDC_ROLES_FORMAT=organization_grants
OIDC_ROLES_ORGANIZATION_ID=<organization-id>
OIDC_REQUIRED_ROLE=access
```

Enable JWT access tokens and project-role assertions. The role mapper accepts only
the configured project-qualified claim and organization; a generic role elsewhere
in the token does not grant access. The management bootstrap script is a separate
ZITADEL adapter and emits the generic OIDC configuration for the local fixture.
Its provisioning PAT is never needed by the panel or Gateway at runtime.

For existing installations, replace `ZITADEL_ISSUER_URL` with `OIDC_ISSUER_URL`,
`ZITADEL_PANEL_CLIENT_ID` with `OIDC_PANEL_CLIENT_ID`, and `ZITADEL_PROJECT_ID` with
`OIDC_AUDIENCE`; translate project/organization into the role settings above.
Runtime does not infer a provider or fall back to old variables. Recreate API and
Gateway together after configuring both; existing deployed containers are unchanged
until redeployment. Local `identity-bootstrap` regenerates its public identity.env.

Reference: [OIDC discovery](https://openid.net/specs/openid-connect-discovery-1_0.html).
