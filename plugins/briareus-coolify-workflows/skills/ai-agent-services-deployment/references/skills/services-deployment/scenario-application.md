# Scenario: Product Monorepo with Frontend and Backend

Load when one repository contains independently changing application components; reference `deployment-layout.md`, `deployment-runtime.md`, `git-backed-infrastructure.md` and `coolify-compose.md` when Coolify parses Compose.

## Preferred split and legitimate combined start

```text
apps/
  frontend/
  backend/
packages/
  shared-contracts/
deploy/
  README.md
  frontend/
    docker-compose.yaml
    docker-compose.coolify.yaml
  backend/
    docker-compose.yaml
    docker-compose.coolify.yaml
  dependencies/
    docker-compose.yaml
    docker-compose.coolify.yaml
```

The root `deploy/README.md` documents the **system**: ownership, entrypoints, deployment order, public routes, environment network, storage, recovery and resource/Watch Path matrix. Do not require a README per leaf when it adds no service-specific information. `deploy/dependencies/` can own PostgreSQL, pooler, Valkey, auxiliary config and bootstrap **together** if their lifecycle is coherent.

Front- and backend that change independently **prefer** their own Coolify resources and Watch Paths. A small MVP may start with one combined Compose resource, CI and deployment for all services; record the decision, coupled-release cost and what will trigger a later split. Grouping is not a deployment error and does not require premature decomposition.

## Build, updates and shared code

| Resource | First Watch Paths to review | Why |
| --- | --- | --- |
| frontend | `deploy/frontend/**`, `apps/frontend/**` | Compose, frontend code and Dockerfile/build context |
| backend | `deploy/backend/**`, `apps/backend/**` | Backend image/source and bootstrap scripts |
| stable dependencies | `deploy/dependencies/**` | Changed dependency image/config, not every backend push |

When a resource **actually consumes** `packages/shared-contracts/**`, add that path to **its** Watch Paths. Shared code should be relatively stable; frequently changing component internals belong to the owning app rather than a constantly triggering shared package. Confirm the entire Docker build context, copied files, lockfiles and generated schemas are watched. Verify the stored globs on each Coolify resource, not just Git declarations.

CI ordinarily runs static checks, lint, types, tests, source security checks, and Compose validation; **Coolify may perform the image build**. There is no default requirement to build and upload images twice. An immutable registry image may be justified for release provenance or fast rollback; pin it, and test that a previous image can be restored. Rebuilding an older Git commit is possible but slower and not always reproducible if external dependencies are unpinned.

## Networking, ingress and credentials

Use a deliberate shared private **network per environment**, with frontend/backend/dependencies attached only where connectivity is required. Internal backend traffic uses service DNS; browser-side JavaScript cannot resolve Docker-only names, so provide a public API route or same-origin proxy as required by the product contract. Only proxy-facing HTTP endpoints need public domains; do not publish DB, Valkey or bootstrap admin ports.

Coolify environment-specific values belong to appropriate scopes. Public-origin keys are Required only when genuinely consumed for OAuth, callbacks or link generation. Stable internal ports/DNS belong in Compose. Use `variable-glossary.md` for approved input names; do not turn user-configurable business settings into deployment ENV.

## Acceptance and future split

Prove changes scoped to frontend do not redeploy dependencies, and vice versa; record actual webhook/Watch Path behavior, not imagined restart semantics. Check affected healthcheck and consumer flows, and verify persistent state survives restart/recreate. When splitting a combined resource, plan network alias continuity, volume names, secret references, domain ownership and rollback **before** changing its Coolify topology. See `scenario-cutover.md`.
