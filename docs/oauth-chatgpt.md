# Direct OIDC authorization for MCP

The Gateway is a resource server. It does not issue tokens, host OAuth endpoints,
register clients, proxy token exchanges or store refresh tokens. Each MCP resource
publishes protected-resource metadata pointing directly at the configured external OIDC issuer.
See [provider configuration](oidc.md); the settings below illustrate ZITADEL.

Register the MCP client in the same ZITADEL project as the panel. For ChatGPT use
`https://chatgpt.com/connector_platform_oauth_redirect` as its exact redirect URI,
Authorization Code + PKCE, public client authentication (`none`), JWT access tokens
and role assertion. Enter that registered client ID in the connector's OAuth
configuration; no Briareus-generated OAuth secret is needed. Other clients require
their own exact registered redirects. No wildcard redirect is accepted by Briareus.

Request `openid`, `urn:zitadel:iam:org:projects:roles` and
`urn:zitadel:iam:org:project:id:<project-id>:aud`; request `offline_access` when the
client supports refresh. Assign the user the role matching `BRIAREUS_NODE_ID`
(for example `tambov`) in the configured organization. This grants Control Panel
and MCP access on that node. There is no default global `access` role.
ZITADEL console Project Owner permissions are not an application role assignment.

Configure the generic `OIDC_*` settings on API/Gateway using the ZITADEL example
in [OIDC configuration](oidc.md). Its API audience is the project ID.
The local verifier requires a project-qualified role claim and a valid JWT access
token; an ID token or a token merely containing the project audience is insufficient.
Public keys are cached; issuer, audience, signature and expiry are checked locally.

This deployment uses explicit client preregistration rather than a local OAuth
proxy or instance-wide anonymous dynamic registration. Endpoint URL audience
isolation is not promised: the node-role assignment authorizes that node
independently of which optional provider services are currently connected.

## Connect providers separately

Use the node HTTPS origin followed by the provider path:

| Provider | MCP path |
| --- | --- |
| GitHub | `/svc/github/mcp` |
| GitLab | `/svc/gitlab/mcp` |
| Playwright | `/web/playwright/mcp` |
| Server (files and terminal) | `/server/mcp` |
| Analyzer-R | `/analysis/mcp` |
| Ghidra adapter | `/analysis/ghidra/mcp` |
| SigNoz | `/observability/signoz/mcp` |
| Coolify | `/infrastructure/coolify/mcp` |

There is no root `/mcp` connector or aggregate Web/Observability MCP. Playwright's
internal and external connections are modes of that one provider, not separate
MCP services. Gateway/API use the shared discovery library and existing Valkey
leases plus private-network health to determine which services are connected;
this is availability information, not an alternative authorization mechanism.

The Control Panel browser is a separate public OIDC client. It persists its
provider-issued state through Pinia/localStorage; valid saved tokens survive
reloads and tabs without another authorization code. A fresh authorization is
needed when there is no usable stored user or its refresh is rejected. MCP
client token persistence belongs to the MCP client rather than Briareus.

## Diagnosing MCP authorization failures

The Gateway validates bearer access tokens, but it does **not** store or refresh
ChatGPT connector credentials. ChatGPT (or another MCP client) owns the refresh
token and its exchange with the OIDC issuer. Request `offline_access` when
registering the client; the Gateway advertises that scope, but a scope in
metadata does **not** prove the client received, stored, or successfully rotated
a refresh token. Check ZITADEL client policy and the client's consent/connection
state separately.

A failed MCP call may return `401 invalid_token` even while the private Server
hand is healthy. Gateway records the registered service ID and a **fixed**,
non-sensitive rejection category after token-verification changes are deployed:
`expired`, `not_yet_valid`, `invalid_audience`, `invalid_issuer`,
`invalid_signature`, `invalid_algorithm`, `invalid_claims`,
`missing_grant`, `provider_unavailable`, `introspection_failed`,
`inactive` or `invalid_token`. No bearer, JWT payload, client ID, user ID,
raw provider error or full resource URL is logged.

Use the recorded category and request time to compare the ZITADEL issuer
settings and client-side OAuth renewal events. An `expired` access token
proves **only** that renewal did not produce a valid token before that call;
it does not establish whether the client failed to try, the provider rejected
a refresh, or the client failed to store the result. An `invalid_audience` or
`missing_grant` points to resource authorization/configuration, not token
expiry. Provider errors indicate verification infrastructure problems.
Reauthorization is a recovery option; do not disable OAuth or expose tokens to
troubleshoot. Historical `invalid_token` entries written before the change
cannot be classified retrospectively.

Existing legacy connector tokens cannot be relabelled as ZITADEL tokens. Connect
the new clean V1 deployment separately; retain Legacy until migration/cutover.

References: [ZITADEL scopes](https://zitadel.com/docs/apis/openidoauth/scopes),
[ZITADEL DCR limitations](https://zitadel.com/docs/guides/integrate/dynamic-client-registration).
