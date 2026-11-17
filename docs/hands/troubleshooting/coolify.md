# Coolify MCP — permissions, secrets and deploy state

**Owners:** [SigNoz/Coolify Hand](../telemetry.md) and the
[Coolify source contract](../../../services/hands/infrastructure/coolify/README.md).
Generic Docker Compose, deployment practice and troubleshooting belong
to the independently installable AI Agent Workflow Skills. This guide
only describes Briareus Coolify MCP semantics.

## 401 versus 403 is not the same failure

A Coolify 401 identifies invalid or expired upstream authentication.
For 403, the Briareus tool reports required API permission
(`read`, `read:sensitive` or `deploy`), but cannot decide from the
status alone whether the real blocker is permission, team role,
selected resource scope or an IP allowlist. Inspect the exact
operator-selected account/resource and required capability. Do not
silently switch accounts or elevate token grants.

`coolify_get_application_logs` and `coolify_get_service_logs`
read **runtime** logs; `coolify_get_deployment_logs` reads the
separate **build/deploy journal**. An empty/403 response from one
is not proof of the other. Even redacted runtime logs can contain
unexpected sensitive application output; inspect disclosure scope.

## Shared/locked variable values are not missing by accident

Briareus deliberately never discloses Shared or locked variable
plaintext. Safe status/masking is not a reveal mode, and an app-local
variable tool must not resolve an upstream Shared reference.
For eligible nonshared, unlocked application values, a two-step,
short-lived, single-use confirmation is needed **plus** operator
approval for the exact key/application. Tool access does not
implicitly grant the right to publish a secret.

## Deployment queued does not mean service ready

`coolify_deploy_application` and `coolify_deploy_service` with
`confirm=true` submit exactly the authorized resource. Record its
deployment UUID, then check final status/build journal, current
container revision/health **and a real MCP consumer call**. A green
build is not sufficient evidence of authorized client success.

Saved Coolify Watch Paths, Compose parser, variables, private network,
Destination and persistent volumes are separate from generated Git
configuration. Check the existing live values before changing anything.
Do not rebuild Dependencies, restart all resources or touch storage
because an unrelated Hand configuration is incorrect.

**Completion:** exact account and grant verified, selected deployment
finished with expected revision, application healthy, authenticated
client accepted, secrets and unrelated resources unchanged.
