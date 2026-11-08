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
| Analysis | `/analysis/mcp` |
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

Existing legacy connector tokens cannot be relabelled as ZITADEL tokens. Connect
the new clean V1 deployment separately; retain Legacy until migration/cutover.

References: [ZITADEL scopes](https://zitadel.com/docs/apis/openidoauth/scopes),
[ZITADEL DCR limitations](https://zitadel.com/docs/guides/integrate/dynamic-client-registration).
