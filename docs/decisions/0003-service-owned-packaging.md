# ADR 0003: Owner-scoped runtime packaging

Status: accepted

## Decision

Group runtime under infrastructure/ and hands/. Focused shared packages
have explicit owners/consumers and stable APIs. Each deployable module owns
Dockerfile, Compose, dependencies/lock, health/start and its migrations.
Internal architecture layers stay inside the owner.

Each MCP module has one catalog directory under Hands, optionally grouped.
Nodes select different subsets without source copies or unrelated restarts.
Watch/build inputs cover only the module and consumed shared packages.
Documentation does not trigger runtime builds.

Watch Paths include the owning source and the exact transitive shared
dependencies. Multiple narrow paths are normal. Shared packages may depend
on other focused shared packages; maintain explicit dependency/consumer
relationships and a single implementation instead of per-module copies.
An MCP-only update replaces only its affected containers; Node and other
MCP modules remain running. An explicit Node restart covers that Node's
managed module set. UI/backend changes never imply a database or Node restart.

## Consequences

Verify source and saved deployment settings separately. Preserve app scope,
contracts, data and rollback during qualified cutover. Publish coherent
locally validated owned batches with hooks/protections; not every source edit.

See [topology](../architecture/infrastructure-hands-shared.md).
