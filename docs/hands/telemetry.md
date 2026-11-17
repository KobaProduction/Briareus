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


## Experimental Rust variant

The separate [SigNoz Rust pilot](../../services/hands/observability/signoz-rust/README.md)
runs locally on a different port for contract comparison and uses the same
private Control Panel account boundary. The Python SigNoz Hand remains
authoritative; the Rust pilot is not an additional catalog entry, active
deployment or permission to change Gateway routing.
