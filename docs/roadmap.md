# Delivery and acceptance boundaries

## Source foundation

Control Plane backend owns private Rauthy integration and human management
scope; the infrastructure Authorization service is retired. Node owns all
session requests/decisions; backend stores Node-wide/Project-wide event
projections and refreshes authoritative active requests through RPC.
First-party control uses shared typed gRPC service/Protobuf contracts with
native gRPC and WSS adapters; browser uses WSS. Standard MCP/provider
interfaces remain their supported protocols.

Node provides explicit common read/write storage for all local Projects
with observation/audit and no per-entry/individual-grant restrictions, while
private Project and analysis stores stay isolated. Panel configures system
tools/versions; Node installs them through consuming image/Compose defaults,
read-only to workloads. These requirements do not claim runtime completion.

Complete infrastructure/Hands organization, focused shared contracts,
private Rauthy integration, Node-local Projects/sessions/Cedar, autonomous
SQLite/PostgreSQL state and Project workspace isolation. Node management
supports native gRPC and WSS/binary Protobuf through shared use cases.
Different Nodes deploy selected MCP module subsets and run without a Panel.
Source includes enforced and auto-approved session-access modes: automatic
approval confirms valid sessions and in-Project actions, while Project
isolation always applies. See [mode contract](architecture/session-access-modes.md).

Source includes upload/download and explicit file/directory transfer
interfaces with source/target Node and Project checks. Interfaces and
health are not proof of accepted deployed behavior.

## Authorized aggregate testing

After every source owner finishes and the user authorizes testing, adapt
tests/fixtures and verify actual consumer paths, local runtime, diagnostics
and aggregate behavior. Hooks/required checks remain enabled. Report host
or dependency failures separately from source defects.

## Batched publication

Publish coherent owned batches after local runtime/lint/type/test/hook
validation of the outgoing revision. No approval per push is required
within the task/approved Dev scope. Avoid tiny pushes and repeated CI.
Verify rollout/real behavior/rollback; no Production rollout or reset is implied.

## Deferred functions

Automatic idle shutdown/cleanup, cross-Node approver delegation, finer
per-action human rights and automatic replication/migration/failover are
outside the first iteration. Explicit transfer does not implement them.

See [topology](architecture/infrastructure-hands-shared.md),
[identity/access](architecture/identity-and-session-access.md),
[storage](architecture/node-storage-and-transfer.md) and
[quality](../scripts/quality/README.md).
