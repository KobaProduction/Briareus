# Scenario: Shared Infrastructure Repository

Load when a repository owns third-party or shared infrastructure used by more than one product, server or environment. The owning infrastructure repository contains the **live copy**; AI Agent Workflow contains reusable sanitized examples, never the production Compose watched directly by Coolify. Read `deployment-layout.md`, `git-backed-infrastructure.md`, and `coolify-compose.md` when applicable.

## Example organization

```text
deploy/
  identity/
    README.md
    zitadel/
      docker-compose.yaml
      docker-compose.coolify.yaml
    gateway/
      docker-compose.yaml
      docker-compose.coolify.yaml
  observability/
    README.md
    collector/
      docker-compose.yaml
      docker-compose.coolify.yaml
  platform/
    README.md
    git-service/
      docker-compose.yaml
      docker-compose.coolify.yaml
```

`identity/`, `observability/` and `platform/` are **illustrative groups**, not required categories. A third nesting level is justified for an actual system with subservices. Put one README at the lowest useful **shared owner** (`identity/README.md` can describe both deployments). Add child README only when its own operations, recovery or parser decisions cannot be described compactly at the parent. Stable third-party containers with one lifecycle may share **one** Compose resource instead of being split into one resource per image.

## Ownership and deployment decisions

1. Discover which services are actually shared, which are dedicated to a consumer, and which contain durable state. Document the owner of initial credentials, backups, upgrades, and public ingress; do not treat every shared component as an independent product.
2. Pick a deployment boundary from update frequency, rollback, trust and data lifetime. An identity service and collector often have separate lifecycles; Postgres plus its pooler may be one unit. Do not create a new Coolify resource just because a Compose file contains two `services:`.
3. In each **new** deployable unit, keep standalone `docker-compose.yaml` and Coolify entrypoint `docker-compose.coolify.yaml`. Prefer tested `extends` and repeat any top-level networks/volumes plus parser-visible ENV/managed-file metadata. Validate the actual parser, not only YAML.
4. Configure the resource's Git source and branch, Base Directory (e.g. `/deploy/identity/zitadel`), Compose Location `/docker-compose.coolify.yaml`, and matching repository-relative Watch Paths (`deploy/identity/zitadel/**`). Repeat per resource. A Watch Path is a **trigger**, not proof every container must be recreated.
5. Use shared variables at the **narrowest actual consumer scope** and distinguish Resource inputs from external Secret Manager authority. Shared keys spanning resources identify the owning service; no unqualified common `POSTGRES_PASSWORD` for unrelated consumers. Keep secret values outside Git and agent-visible File Mounts.
6. Before cross-resource internal DNS, verify both resources join the **same actual Docker network** on the correct server. Use Coolify's Connect To Predefined Network where needed; a Destination display name is insufficient. Never connect dev to prod merely for easier DNS.
7. Prove a new or updated resource from source → parser → container/health → actual consumer (issuer, API, metric receiver, etc.), with persistent-volume and rollback evidence. Do not infer that a successful deploy proves a working external service.

## Reusing and maintaining upstream examples

Copy a vetted `examples/services/` preset into the private infrastructure repository, record the source revision, review local differences, and attach Coolify to **the copy**. Upstream changes are never auto-synced into production. When the local agent learns a reusable lesson, strip hostnames, secrets and project topology, test the generalized example, propose a change upstream in AI Agent Workflow and obtain operator approval before publishing. An existing proven single-Compose preset need not be bulk-migrated merely for file naming style.

## Stop or choose another pattern when

- The service is dedicated to one application: see `scenario-application.md`; it may belong in that product's `deploy/` tree instead.
- A live stateful deployment is being moved from UI ownership: consult `scenario-cutover.md` before any resource recreation.
- The intended Compose inheritance/parser version is unverified: document that gate rather than trying it by recreating production.
