# External services — Rauthy, PostgreSQL and Valkey

The intended infrastructure-only shared vendor unit contains **Rauthy, PostgreSQL and Valkey**. It does not package Control Plane UI/backend, Node Gateway or MCP Hands into one product container/application.

Rauthy is the human identity authority and creates its initial administrator during empty-provider initialization. Backend privately implements supported provider/session/MFA/OIDC continuations. Never derive an administrator password from logs, replace the provider's credentials on a missing local projection, or treat an infrastructure admin as Node/Cedar session authority.

Existing PostgreSQL/Valkey volumes, Rauthy state, secret bindings, network and allowlisted Dev app identities are protected through migration. The target layout is not authorization to create a new application, reset data, rebuild all modules, inspect plaintext secrets or switch a production resource.

Only the specifically approved Development environment and UUIDs in [the strict scope policy](../operations/BRIAREUS_DEV_ACCESS_SCOPE.md) may be inspected or changed. Source plans and resource health are not sufficient proof of a working human login.

Details: [external service owner](../services/external/README.md), [identity](identity-and-human-authority.md), [deployment](../deployment.md), and [rollout procedure](../operations/development-rollout.md).
