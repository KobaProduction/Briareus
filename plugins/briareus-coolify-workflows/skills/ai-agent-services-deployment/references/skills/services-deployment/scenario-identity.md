# Scenario: Shared or Product-owned Identity Service

Load when deciding where an OAuth/OIDC identity provider and its auxiliary gateway/login processes live. This is an **ownership/deployment pattern**, not a vendor-specific ZITADEL bootstrap guide; configuration, first-admin handling and migration details belong to the provider's owning runbook. Consult `scenario-infrastructure.md` or `scenario-application.md` depending on the chosen owner, and `coolify-networking.md` for public routes.

## Choose the owner

| Choice | Where to place Compose | Consumers / lifecycle |
| --- | --- | --- |
| Shared identity infrastructure | `infrastructure/deploy/identity/provider/` | Multiple applications or environments under one provider authority; changes coordinated with all consumers |
| Dedicated identity for one product | `product/deploy/identity/provider/` or `product/deploy/dependencies/` | Only that product, with its own credentials, stable issuer and environment network |

Both are legitimate. For a small app, a dedicated provider may share a single Compose resource with stable dependencies; split it only if operational/identity isolation, update frequency or backups justify a separate resource. A provider needing a gateway, web login adapter or other helper may use a three-level functional layout under `identity/`, with **one parent README** covering the related resources. Do not create a README per tiny helper unless it has an independent setup/rollback contract.

## Public vs private surface

The identity provider's issuer URI and OAuth endpoints are **external identity contracts**. Before generating domains, map actual consumers and all required routes: issuer/discovery/JWKS, login, authorization, token, logout, redirect callbacks, and API-specific public endpoints. Route each to the correct Compose service and internal port; do not conflate an OAuth provider with a separate API/MCP gateway.

Keep databases, administrative/batch interfaces and private identity-backend connections on the environment's internal network. Declare **one** managed public route using the `SERVICE_URL_*` preference in `coolify-networking.md`, or `SERVICE_FQDN_*` instead when the provider needs a hostname-only setting. If the provider's required issuer/public origin matches that route, derive it from the generated value **only after verifying** interpolation and the actual issuer/discovery/redirects. Set a separate approved public-origin input only when the provider requires a distinct value or the deployed Coolify parser demonstrably cannot supply a correct one; this is an explicit exception, not an automatic second Required URL. TLS/certificate issuance does not require both magic variables.

## ENV/credential authority

- The provider has **its own** canonical upstream parameters and vendor setup. Operator keys use only approved names, mapping them to upstream ENV at a real consumer boundary. General `services-deployment` doesn't prescribe default admin users or create bootstrap-specific ZITADEL keys.
- An identity provider may use a project-owned PostgreSQL or a shared DB; choose credentials scoped to the **actual principal**. Shared names must qualify ownership when ambiguous. Store master keys, signing private keys and passwords with approved secret authority; never invent or print them.
- Keep the provider's signing/encryption material stable across redeploys; changing it can invalidate tokens or encrypted state. Environment separation requires different trust/material where appropriate, but not pointless environment suffixes if scopes already separate.

## Adoption and upgrade

1. Confirm which product already trusts the issuer, which public routes actually exist and which services hold durable identity state. Moving a dedicated instance to a shared owner is a real **trust boundary/migration**, not a directory rename.
2. Choose base Compose and Coolify entrypoint, Git branch, Watch Paths and per-environment network; verify effective `extends`, secrets and persistent volumes without touching live state.
3. Validate a **fresh test instance** against its own sign-in/issuer consumers, then plan migration/cutover with explicit approval. Never reuse active identity secrets or public issuer address in an unapproved disposable experiment.
4. Acceptance is real issuer discovery, expected token signature/audience, browser redirect and consumer authentication, not just a login UI or green container. Restore prior routing/keys/database access on failed cutover; token signing-key rollback may need overlap.

Publish only sanitized, tested shared/dedicated provider presets to AI Agent Workflow `examples/services/` when the operator requests it. Keep private domains, users, resource IDs and credentials in the owned infrastructure repository.
