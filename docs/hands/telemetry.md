# SigNoz and Coolify Hands — observability and controlled operations

**Catalog:** `signoz`, `coolify`. **Sources:** [SigNoz](../../services/hands/observability/signoz/README.md) and [Coolify](../../services/hands/infrastructure/coolify/README.md).

SigNoz remains a read-only telemetry provider at `/observability/signoz/mcp`.
Coolify is a separate infrastructure Hand at `/infrastructure/coolify/mcp`,
providing metadata, deployment/build journals, application runtime logs,
variable status and deliberately authorized restart/deploy actions. There is
no combined Observability MCP.

## Privacy and permission boundary

Coolify uses the explicitly selected encrypted Control Panel API account.
Container runtime logs require Coolify `read:sensitive`; they are bounded and
best-effort redacted, with their text omitted from invocation audit. Reading
configuration is more restricted:

- **Shared Variables:** only configured/presence, length and optional irreversible
  first-two/last-two mask; never raw values, never reveal locked values.
- **Application variables:** metadata by default. Full reading of one nonshared,
  unlocked variable requires separate prepare and confirm MCP calls, an
  operator permission assertion, and a short-lived single-use challenge.
- **Mutations:** restart one application/service or deploy one app only with
  `confirm=true`, selected resource scope and upstream `deploy` permission.

Coolify API permissions, resource scope and human/operator authority are
independent. Successful Coolify API authentication alone does not permit
agents to publish secrets or restart unrelated resources. No physical host
reboot is offered. See [exact endpoint and scope contract](../../services/hands/infrastructure/coolify/README.md), [deployment](../operations/deployment.md) and [configuration](../operations/configuration.md).

SigNoz logs/traces and Coolify deployment/container logs are different views.
Observability data and queued deployment responses are not evidence of complete
consumer acceptance. Do not expose plaintext secrets through logs or tool-call audit.

## Coolify workflow skill

The Coolify Hand publishes its Briareus-specific
`coolify-deployment-workflow` Skill from its own source. It documents account
selection, scoped permissions, log privacy, safe variable handling and explicit
authorization of individual deploy/restart operations. Clients without Skills
support can read the same local guidance using `read_project_workflow`.

Generic Docker Compose and deployment methodology is distributed by the
independent AI Agent Workflow marketplace. Neither Coolify MCP startup nor
its Docker build downloads those universal documents.

## Active Rust SigNoz backend on tambov

The [Rust SigNoz Hand](../../services/hands/observability/signoz-rust/README.md)
serves the existing `/observability/signoz/mcp` Gateway route using the
same Control Panel provider accounts and private identity boundary.
The Python SigNoz resource is stopped but retained for rollback.
The canonical V1 catalog still names Python source and must be reconciled
before removing the fallback. OpenTelemetry exporter support is implemented
in Rust, but the current cutover has no configured production OTLP endpoint:
full collector delivery and propagated spans require separate acceptance.
