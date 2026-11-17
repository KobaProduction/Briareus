# Node identity and external authorization — V1

## Separate node deployments

Each V1 installation is a **single-server node**, with its own Gateway, Control Panel UI/API, selected Hands, PostgreSQL data, private network and persistent workspaces. `BRIAREUS_NODE_ID` is the required node name and **external identity-provider role**; it is independent of the node's public DNS origin. API and Gateway must be configured with the same value, for example `tambov` or `morshansk`.

Different nodes share a configured external OIDC issuer but **not** their node role, physical database, persistent volumes, environment Destination or browser profile. Configure distinct panel redirect and logout URIs per node using its exact `/admin/` origin. The provider role is assigned by an administrator; a successful browser sign-in alone does not grant access to every node.

This is the V1 node identity contract; it **does not implement V2 autonomous Node/Project/session administration or cross-node transport**.

## Provisioning and resource verification

Control Panel API prepares an existing or missing node role through its provider adapter before exposing readiness. API owns the protected `OIDC_PROVISIONING_TOKEN`; Gateway/Hands/UI must not receive it. Role preparation must preserve existing provider assignments rather than clearing or recreating users. Failed provisioning blocks API readiness.

The UI uses Authorization Code + PKCE with provider-issued identity. Gateway/API verify token lifetime, issuer, audience and role; JWTs are verified using JWKS by default. Opaque tokens require explicitly configured RFC 7662 introspection credentials. A configured role or a valid API audience without the required node grant is insufficient. MCP clients are separately preregistered and own their own refresh lifecycle.

## Operational checks

Check the actual identity provider's registered client callbacks, node grants, startup readiness and authenticated MCP call. Do not expose the token, issuer secret or provider error payload during diagnostics. Prefer sanitized rejection categories and request time; a `401` from Gateway is not proof that Server/Hand is unhealthy.

Detailed contracts: [OIDC](../oidc.md), [MCP/ChatGPT authorization](../oauth-chatgpt.md), [configuration](configuration.md), [Control Panel](../services/control-panel.md).
