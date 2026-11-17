# Deployment Layout and Reusable Presets

Load for new service or infrastructure repository layout, Git-backed adoption, directory moves, or designing Watch Paths. One standard serves both infrastructure repositories and application monorepos; **grouping differs by ownership and update lifecycle**. Do not migrate an established layout without approval.

## Deployable ownership, not arbitrary nesting

Use `deploy/` for repository-owned deployment definitions, normally `deploy/<service>/` or `deploy/<domain>/<service>/`; add a third only for justified system ownership. Group by **function**, not orchestrator; no mandatory `deploy/coolify/`. Useful functional areas include `identity/`, `observability/` or an application-specific system. Do not require `databases/`: databases are often dependencies.

Infrastructure repositories may host a shared identity provider, while product repositories may carry a dedicated identity provider beside frontend and backend. A shared provider and a service-owned provider are different ownership and upgrade contracts, even if using the same image.

## Update boundaries

- A resource is **not** required for every container. Prefer grouping stable dependencies with the same lifecycle (`PostgreSQL`, `PgBouncer`, migration helper, etc.) into a `deploy/dependencies/` Compose stack where safe. Split only for independent lifecycle, trust, backup, scaling or resource constraints.
- Separately changing first-party frontend/backend **preferably** have independent deployment directories/resources/Watch Paths, often `deploy/frontend/` and `deploy/backend/`. A single smaller stack is legitimate for fast delivery; record the reason and split trigger rather than forbidding it.
- Preserve explicit persistent data authority, ownership, resource limits and trust boundaries; not every container needs an independent volume or network.
- Use one documented entrypoint per Coolify resource. A multi-service Compose resource may have multiple containers and a bootstrap helper.

## Files and READMEs

For a **new standard deployable source**, provide a generic `docker-compose.yaml` and the Coolify-specific `docker-compose.coolify.yaml`. Use four-letter `.yaml` exclusively in newly authored standard paths. Base Compose must describe a usable non-Coolify topology; orchestrator-specific interpolation, routing, managed files and Shared refs belong in the Coolify entrypoint. Choose and test a supported `extends` / `include` / composition mechanism under the actual Coolify parser; filename alone does not merge source files. Block release if one effective input is omitted, parser discovery fails or real generic Compose cannot be recovered. Do not duplicate manifests without a synchronization test.

Place a **single README at the lowest useful common parent** explaining the related deployment units and setup. For `deploy/<system>/gateway/` plus child helper stacks, prefer `deploy/<system>/README.md` if it can describe them accurately; add a per-resource README only for materially independent installation/ownership or complex parser, migration and recovery detail. The owning README records repo/branch, Base Directory, Compose Location, Watch Paths, variable/secret ownership without values, networks, data/backup, prerequisites, validation and rollback. Documentation need not be colocated with each Compose file.

## Git-backed updates

For a resource at `deploy/backend/`, the default Watch Path is `deploy/backend/**`, including README. Docs-only changes can cause harmless redeploy: avoid brittle per-file exclusions by default. Watch Paths are repository-relative, one pattern per line, and **must be explicitly saved and verified on the resource**. A webhook alone does not replace Watch Paths. For shared packages or templates outside the service folder, add only the actually consumed paths (e.g. `packages/shared-contracts/**`) and validate effects. Keep frequently changing code inside its owning service; extract shared source only when stable enough for a genuinely shared lifecycle. Check the actual build context and source dependencies, not just Compose paths. Full Watch Path semantics belong to `git-backed-infrastructure.md`.

## Presets, copying and upstream feedback

The public `AI Agent Workflow/examples/services/` catalog is the **reusable upstream** for project-neutral, independently described and tested examples, including distinct patterns for shared and private identity systems. Infra repos **copy** the selected preset into their own `deploy/` tree, record source/revision and adapt it there. Never point live production directly at moving example HEAD. Pull upstream changes through diff, compatibility review and acceptance; no automatic template-to-prod synchronization. When agent work yields a generally reusable fix, propose and contribute a sanitized improvement to AI Agent Workflow, with evidence and independent review. Do not export private topology, domains, credentials or deployment state.
