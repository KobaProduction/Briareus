# Scenario: Adopt, Split or Recover an Existing Deployment

Load when changing an **already running** UI-owned, Git-owned or monolithic deployment: copying a preset, creating a Git-backed Coolify resource, splitting frontend/backend, adding PgBouncer, moving identity ownership, changing networks, or rolling back. Consult `deployment-lifecycle.md`, `coolify-migrations.md`, `git-backed-infrastructure.md` and `coolify-validation.md` if needed. No implicit redeploy authorization.

## Discover before designing

| Live authority | Capture the effective contract |
| --- | --- |
| Git | Source repo/branch/ref, base/Compose location, consumed Dockerfiles and Watch Paths |
| Coolify/parser | Resource type, Compose parsing version, saved ENV/Shared refs and flags, domains, managed File Mount records, deployed Compose |
| Docker | Actual networks/aliases, named **physical** volumes, images, health/restart policies, live containers |
| Consumers | Public route, issuer/callback, database DNS, queue and durable state owner, integration flows |

The file in Git is **not** evidence of the runtime values or volume identity. Existing Coolify File Storage can override updated `content:`; parser-generated or deleted variables can persist. Capture owner-scoped secret **references**, never plaintext. Record last known good deployment and backup before modifying the existing one.

## Choose a safe change path

**1. New, empty install** — copy the reviewed source to the owning repo; validate standalone Compose and Coolify inheritance/parser in an isolated resource, then supply approved scoped secrets and network/domain definitions. Deploy after real operator permission. No existing data is assumed.

**2. UI-owned → Git-owned state** — compare effective UI Compose/files/variables with proposed Git input. Preserve domain ownership, File Mount content, durable volume names, auth principals, and generated parser entries. A new resource may allocate a different physical volume for the same Compose key `postgres-data`. Explicitly plan state migration; do not create an empty database over production data.

**3. One resource → several** — document update boundaries and replace only approved pieces. Review Compose service renames, Docker networking, shared aliases, publicly visible route, secret references, storage ownership and whether simultaneous old/new writes can corrupt state. Keep `deploy/README.md` as owner of the multi-resource map; confirm each resource's own Watch Paths and build source dependencies. Moving files alone does not move containers or persistent data.

**4. PostgreSQL direct → optional PgBouncer** — preserve application endpoint `database:5432`, making the alias belong to PgBouncer when enabled and PostgreSQL when disabled. Verify that the actual clients, initialization jobs and admin operations can use their intended direct/pooler route. Preserve server internal port and data volume. Switching aliases in live multi-resource environments is a **cutover**, not a default deployment side effect.

**5. Changed provider/issuer or secret** — verify downstream consumers and compatibility. Rotating a signing key, moving identity instance or switching secret authority can invalidate live tokens or encrypted data; not resolved by rolling back Git alone.

## Acceptance and rollback matrix

| Change | Prove before cutover | Failure recovery |
| --- | --- | --- |
| Compose parser/ENV | Correct Required/default values, shared references, file mounts and networks on disposable/test resource | Restore prior resource definition; do not delete working runtime |
| Monorepo split | Independent Watch Paths, no unrelated restart, network and route reachability | Restore old routing/entrypoint after stopping writes to new owner |
| Stateful volume migration | Backup/restore evidence, single active writer, database compatibility | Restore snapshot/data owner, not only image tag |
| Shared DNS/pooler | Only one alias owner, same app-facing endpoint, successful connections | Revert alias to direct PostgreSQL and validate clients |
| Service update | Health and real-consumer operation after selected commit/image | Redeploy pinned last-good image or rebuild prior Git ref if dependency state permits |

Never run competing writers or collectors against one state owner. Preserve one clear routing and storage owner; stage only with operator approval. A Coolify deployment marked `finished` is not proof that data, OAuth, callbacks, remote telemetry or backup recovery work. If a nonproduction experiment cannot prove the parser/network semantics, report the unresolved blocker rather than experimenting on live resources.

## Reusable feedback loop

After a successful local change, suggest a **sanitized** generic scenario/preset improvement to AI Agent Workflow. Copy it upstream only on explicit operator instruction. Never point a live resource at moving workflow-example HEAD, and never sync public templates into private infrastructure automatically.
