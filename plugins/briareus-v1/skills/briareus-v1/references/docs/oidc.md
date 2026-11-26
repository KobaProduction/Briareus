# External OpenID Connect providers

Briareus is an OIDC public client and an OAuth resource server. It does not host an
identity provider. The panel uses `oidc-client-ts`, Authorization Code + PKCE S256,
discovery and account selection without ending the shared identity session. API and MCP Gateway validate signed JWT access
tokens locally by default. Optional `OIDC_TOKEN_VERIFICATION=introspection`
uses the issuer's RFC 7662 endpoint and configured resource-server credentials;
opaque tokens are supported **only** in that explicitly configured mode.

## Application configuration

Keep the canonical, non-secret `OIDC_ISSUER_URL` in Team Shared Variables
when Briareus and other applications share the same issuer; each authorized
Gateway/API resource must explicitly reference it through its own
`OIDC_ISSUER_URL` environment input. Keep audience, client ID, node-specific
roles and their claim mappings at application/resource scope. API and Gateway
must enforce the same issuer, audience and node/organization authorization policy.
Their verification methods can differ: the deployed API uses JWT, while Gateway
can use introspection. Never reuse provider
administration or token introspection credentials merely because the issuer
is shared.

| Variable | Meaning |
| --- | --- |
| `OIDC_ISSUER_URL` | Exact issuer, including realm path when applicable; HTTPS in production |
| `OIDC_AUDIENCE` | API audience present in access tokens; separate from the public panel client ID |
| `OIDC_CLIENT_ID` | Per-resource registration: public browser client in Control Panel API; confidential resource client in Gateway when needed |
| `OIDC_CLIENT_SECRET` | Gateway client authentication in introspection mode only; protected, never sent to UI |
| `OIDC_TOKEN_VERIFICATION` | Gateway operator selects JWT or introspection according to actual provider token contract |
| `OIDC_JWT_ALGORITHMS` | Explicit CSV asymmetric allowlist, default `RS256` |
| `OIDC_ROLES_CLAIM_PATH` | JSON array of literal claim path segments, default `["roles"]` |
| `OIDC_ROLES_FORMAT` | `list` (default) or `organization_grants` |
| `OIDC_ROLES_ORGANIZATION_ID` | Required only for organization-bound grants |
| `BRIAREUS_NODE_ID` | Required node identity and role; same value on API and Gateway, no default |

API also requires public `OIDC_PROVISIONING_PROVIDER=zitadel` and the protected
`OIDC_PROVISIONING_TOKEN` for automatic role preparation at startup. The token belongs
only to API; keep its value in Shared Variables and reference it from the resource.
The role is created only if missing. Existing roles and assignments are reused.

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
OIDC_CLIENT_ID=<resource-specific-client-id>
OIDC_ROLES_CLAIM_PATH=["urn:zitadel:iam:org:project:<project-id>:roles"]
OIDC_ROLES_FORMAT=organization_grants
OIDC_ROLES_ORGANIZATION_ID=<organization-id>
BRIAREUS_NODE_ID=tambov
```

The application requests the established OIDC identity and refresh scopes. For the
explicit ZITADEL project-qualified role mapping, it derives the role and audience
scopes from the configured audience; these are not deployment variables. Enable
JWT access tokens and project-role assertions. The role mapper accepts only
the configured project-qualified claim and organization; a generic role elsewhere
in the token does not grant access. The management bootstrap script is a separate
ZITADEL adapter and emits the generic OIDC configuration for the local fixture.
Its provisioning PAT is never needed by the panel or Gateway at runtime.

## Client naming and migration

Each Coolify resource uses canonical client keys. Do not copy a public browser
client ID into Gateway or expose a Gateway secret in the panel. The generic
multi-resource Compose reads `CONTROL_PANEL_OIDC_CLIENT_ID` and
`GATEWAY_OIDC_CLIENT_ID` / `GATEWAY_OIDC_CLIENT_SECRET` at the shared local ENV
boundary, then maps them to canonical container inputs. The local identity
bootstrap regenerates its public identity.env. In direct API deployments with a
genuinely separate introspection registration, the verifier uses
`OIDC_RESOURCE_CLIENT_ID` and `OIDC_RESOURCE_CLIENT_SECRET`; these are not
default Coolify inputs and must not reuse the public client.

Before publishing to an automatically deployed branch, reconcile existing
`OIDC_PANEL_CLIENT_ID` and `OIDC_INTROSPECTION_CLIENT_ID` /
`OIDC_INTROSPECTION_CLIENT_SECRET` with their canonical resource-local keys.
Keep existing registrations, privileges and secret references. Do not unlock,
reveal, or rotate protected credentials merely to rename them. For a locked
credential, the authorized operator must provide its protected canonical
reference through the supported secret-management process. Do not remove old
saved values until rollback is no longer needed. Check both nodes independently,
including issuer, audience, organization and role policy, derived scopes,
browser login/renewal and real authenticated MCP calls. A source change is not a
saved Coolify configuration migration.

The verification strategy, asymmetric allowlist and role mapping are retained
as explicit supported-provider policy inputs pending a reviewed provider
adapter contract. Never silently switch JWT/introspection or weaken role
checks in a naming migration.

Reference: [OIDC discovery](https://openid.net/specs/openid-connect-discovery-1_0.html).
