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
client supports refresh. Assign the user the single project role `access` in the
configured organization. This grants full Control Panel and all MCP access.
ZITADEL console Project Owner permissions are not an application role assignment.

Configure the generic `OIDC_*` settings on API/Gateway using the ZITADEL example
in [OIDC configuration](oidc.md). Its API audience is the project ID.
The local verifier requires a project-qualified role claim and a valid JWT access
token; an ID token or a token merely containing the project audience is insufficient.
Public keys are cached; issuer, audience, signature and expiry are checked locally.

ZITADEL's current DCR places clients in a separate project and ignores `resource`.
This deployment uses explicit preregistration rather than reintroducing a local
OAuth proxy or enabling instance-wide anonymous registration. Endpoint URL audience
isolation is not promised: authorized users have full project access by design.

Existing legacy connector tokens cannot be relabelled as ZITADEL tokens. Connect
the new clean V1 deployment separately; retain Legacy until migration/cutover.

References: [ZITADEL scopes](https://zitadel.com/docs/apis/openidoauth/scopes),
[ZITADEL DCR limitations](https://zitadel.com/docs/guides/integrate/dynamic-client-registration).
