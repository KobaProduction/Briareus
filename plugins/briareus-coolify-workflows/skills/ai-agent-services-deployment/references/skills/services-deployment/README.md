# Services Deployment

Load for Git-backed services deployment, Docker Compose, runtime dependencies, networks, infrastructure migration and orchestrator-managed services. This is the single current deployment skill; do not introduce versioned parallel contracts. Select only modules relevant to the current operation; do not load the entire folder.

## Route by work

- **New layout / first adoption / infrastructure or app monorepo** → `deployment-layout.md`.
- **Generic Docker Compose packaging** → `docker-compose.md`; for build, images, CI/runtime, bootstrap or grouping dependencies → `deployment-runtime.md`.
- **Git-owned deployments and Watch Paths** → `git-backed-infrastructure.md`.
- **Coolify owns Compose parsing** → `coolify-compose.md` **mandatory**, then its conditional links for ENV, secrets, networking, managed files, migrations and parser acceptance.
- **New service lifecycle, upgrade, recovery, host privilege or migration** → `deployment-lifecycle.md`.
- **Deciding whether ENV is necessary** → `environment-policy.md`; **Coolify parser variables** → `coolify-variables.md`.
- **New operator/Shared/secret key or naming mismatch** → `variable-glossary.md`; **OpenTelemetry naming** → `telemetry-variables.md` (both on demand). Names not covered there still need approval; never auto-rename live keys.
- **S3 or SMTP operator keys** → `integration-variables.md`; **PgBouncer as optional PostgreSQL proxy** → `pgbouncer-deployment.md` (only when relevant).
- **PASSWORD / TOKEN / KEY / SECRET naming** → `credential-variables.md` when designing credential contracts.
- **Public reusable deployment presets** → `../../examples/services/README.md` after loading relevant deployment module.
- **Shell, SSH or human-operated commands** → `../terminal-operations.md`.
- **Implementation or code changes** → `../software-engineering/README.md`.
- **Independent review** → `../code-review.md`.
- **Infrastructure MCP/tooling strategy** → `../../docs/MCP_STRATEGY.md`.

## Worked deployment scenarios (load only matching case)

- **Shared infrastructure and reused presets** → `scenario-infrastructure.md`.
- **Application monorepo, independent frontend/backend and shared code** → `scenario-application.md`.
- **Grouped stable dependencies, PostgreSQL/PgBouncer/Valkey** → `scenario-dependencies.md`.
- **One-shot bootstrap / schema or provisioning prerequisites** → `scenario-bootstrap.md`.
- **Shared vs dedicated identity provider and public routes** → `scenario-identity.md`.
- **Infrastructure/App telemetry and Coolify-managed configuration** → `scenario-telemetry.md`.
- **External S3/SMTP/OAuth integrations and protected credentials** → `scenario-integrations.md`.
- **Adopt/split an existing resource or restore from a failed change** → `scenario-cutover.md`.

## Core invariants

Discover the actual topology and ownership before change; use the existing orchestrator, not a parallel control plane. Keep project-specific addresses, paths, secret values and runtime IDs out of this public skill. Separate Git desired state, Coolify/parser state, Docker/container state and real-consumer acceptance. Preserve durable data and least privilege. Before risky redesign freeze one-entrypoint semantics, steady state, persistence/backup, rollback, bootstrap behavior and required acceptance. Cover clean installation, repeat deploy, partial state, restart, migration and rollback when applicable. Discussion and proposals do not authorize edits to deployments or live infrastructure; change only what the operator explicitly requests. Reuse and return generalized, sanitized improvements to AI Agent Workflow rather than copying private live configuration.
