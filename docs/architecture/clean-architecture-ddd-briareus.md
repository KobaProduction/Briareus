# Mandatory Clean Architecture / DDD for Briareus

Owner decision: 2026-10-21. This is the engineering contract, not a task list.

## Required source and read order

1. Root `AGENTS.md` and the owner topology it references.
2. This Briareus adoption contract.
3. [AI Agent Workflow: Clean Architecture and DDD](ai-agent-workflow/clean-architecture-ddd.md).
4. [Local quality policy](../../scripts/quality/README.md).

The reference is an unmodified MIT-licensed copy of
`ArthurKoba/ai-agent-workflow/skills/software-engineering/clean-architecture-ddd.md`
at commit `579c51af744c47d2cc8a378ab744a1955298268a`, blob
`79b229b14f5f3a11f3dceff9f2bf16f9066e0d50`.
[Pinned upstream](https://github.com/ArthurKoba/ai-agent-workflow/blob/579c51af744c47d2cc8a378ab744a1955298268a/skills/software-engineering/clean-architecture-ddd.md),
[license](ai-agent-workflow/LICENSE). Upstream reference examples do not override
Briareus's stricter typed-result, authority, protocol or data-preservation rules.

## Apply inside existing owners

Runtime ownership is grouped under `infrastructure/` and `hands/`, with
focused reusable `shared/` packages. Every service is its own bounded context. Introduce `domain`, `application`, `infrastructure`
and presentation modules INSIDE that owner's existing import/package root.
Preserve deployed entry points and wire contracts while replacing their internals.
Do not move business services into a cross-owner shared package or create a
global repository, universal domain model, shared ORM session or shared migration.

- Domain: framework-free dataclasses, entities, UUID/value objects, aggregates
  with actual invariants, policies and facts expressed as domain events.
- Application: typed commands/queries/results, one use case per scenario,
  dependency-injected ports, transaction and idempotency orchestration.
- Infrastructure: repository/UoW implementations, SQLAlchemy/Valkey, Rauthy and
  provider clients, filesystem/Docker/process implementations, event persistence.
- Presentation: thin FastAPI/WS/gRPC/MCP adapters, boundary validation,
  error mapping and serialization, followed by the application call.
- Composition root: concrete wiring and process startup, outside domain/use cases.

Domain imports only its own domain and the standard library. The sole exception
is an explicit import of `owner_protocol.domain.authority._uuid_v4`, optionally
aliased or bound as `staticmethod`, to replace existing identical UUIDv4 predicates.
This stdlib-only `object -> bool` predicate performs no parsing or coercion; it
authorizes no other shared domain, business, ORM, model or framework imports.
Application depends on its domain and port contracts, not FastAPI/SQLAlchemy/httpx/provider SDKs.
Infrastructure implements inward-facing ports. Presentation consumes application
contracts. A mechanical file split that leaves the same outward dependencies or
duplicate logic is not an architectural refactor.

Technical gateways/executors still use explicit application orchestration and
ports, but do not invent business entities/aggregates for each socket or SDK call.
Create an abstraction only where it protects a real boundary/invariant or removes
real duplication. No event bus/CQRS/outbox rewrite just to reproduce a diagram.

## UI and contracts

UI keeps FSD layers: app -> pages -> widgets -> features -> entities -> shared.
Entities own typed state/value transformations, features own user workflows,
widgets compose features, shared holds reusable UI and transport primitives.
Avoid cross-slice imports and public-API sidesteps. Shared never imports a feature.
Move reusable logic to its lowest valid owner, not to a generic dumping ground.

All Python public functions require typed inputs/results. No Any, bare generic
containers, ordinary dict/Mapping results or model_dump/asdict result facades.
Use a named dataclass, NamedTuple or boundary model; serialization is performed
at the outer adapter as input to the external library, without leaking a generic
dictionary through the application contract. Preserve externally specified MCP,
OIDC, event and gRPC schemas; do not rename deployed fields for stylistic reasons.

Production cognitive complexity <=15; tests <=30. Do not raise thresholds, add
blanket suppressions, baseline existing debt away, truncate tests or weaken
authorization checks outside the explicit Node session-access mode contract.
Support configured automatic approval without weakening unconditional Project
isolation, session lifecycle or human management authority; see
[session-access modes](session-access-modes.md). Keep fail-closed handling
of unavailable required state and UUID/replay semantics.

## Integration and evidence

Agents have explicit exclusive file ownership and communicate contract changes
before touching another lane. Root owns shared policy/coordination and aggregate
acceptance. Preserve all peer work. Agents may publish coherent owned batches
after local runtime/static/test validation and mandatory hooks; do not push
each extraction or trigger repeated CI. Source-first work and separately
authorized aggregate testing precede publication validation. No live reset,
secret inspection or Production change follows from architectural extraction.
No task Markdown artifacts.

Remove incompatible historical implementations and obsolete compatibility
aliases after resolving their actual source/build/dynamic consumers. Do
not carry rejected architecture forward to satisfy legacy tests. Useful
algorithms/invariants remain with their correct owner; owner-specific
Files/Terminal/Analysis orchestration does not belong in a universal shared
client. Delete tests exclusive to the removed/incompatible legacy contract;
preserve tests of applicable invariants and never delete a test to hide a
current defect. This cleanup does not authorize a broad frontend rewrite.

Complete foundation/source work across ALL owners before the separate later
test phase. Scoped Biome/Ruff/mypy/type, complexity, result-contract and
import-boundary static diagnostics are allowed as needed during source work.
Do not run, write or adapt new/retained tests or fixtures during this source phase;
removal of proven obsolete legacy tests is authorized source cleanup. Initial
diagnostic tests and per-block acceptance are not exceptions. Test/fixture
adaptation and final aggregate acceptance begin only in the separately
authorized next phase after all owners finish their source work. Do not run
tests/builds after every function or extraction. Mandatory quality hooks remain
enabled. Source-phase diagnostic tests and per-module test acceptance are
not separate exceptions to the aggregate authorization boundary.
Classify unsupported-host/dependency failures
separately from source defects; never report a stopped/failed check as success.
No whole-project completion claim until every current source owner has been
reviewed, refactored where needed and verified against its actual consumer paths.
