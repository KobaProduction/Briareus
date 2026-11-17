# Runtime, Build, Dependencies and Bootstrap

Load when selecting build/release strategy, defining health or bootstrap order, or grouping dependencies. No universal rule requires a prebuilt registry image: a Git-backed Coolify project may run CI format/lint/type/test gates while Coolify builds on deployment. Use published immutable images where rollback speed, supply-chain provenance or multiple targets justify them. Git revision rebuild is an alternative with different recovery time and dependency reproducibility; decide and test explicitly.

## Grouping and lifecycle

Stable third-party dependencies (for example PostgreSQL with PgBouncer, pgAdmin, Redis or a collector) may share **one** Compose entrypoint and Watch Path under `deploy/dependencies/`. Do not create a Coolify resource per container by default. Split only when lifecycle, privileges, scaling, independent ownership or update behavior justify it. Frontend and backend independently developed are *preferably* separate deployable resources, but a small or short-lived product may deliberately combine them for speed; record the tradeoff and future split condition.

For one-shot database initialization, migrations or first-admin provisioning, use a purpose-built bootstrap container/job when needed. Define idempotency, state authority, permissions, health/completion gate (`service_completed_successfully` only where supported), repeated deployment and failure behavior. Prevent backend startup before a required bootstrap completes. Do not assume a one-shot job is automatically re-executed on every update; validate the actual orchestrator lifecycle. Never log setup secrets.

Network planning: prefer a shared private application network within one environment and network isolation across environments; use Docker service DNS. Shared dependencies may require explicitly approved cross-resource attachment; never infer attachment from a network's display label. Avoid exposed DB/admin ports without an external consumer. Preserve stable persistent storage and rollback dependencies.

## Images and builds

- Choose the deployment source explicitly: CI may run lint/types/tests and Coolify may build from a pinned Git commit; alternatively CI may publish a pinned image when faster rollback, immutability or provenance matters. Neither strategy is mandatory.
- Pin image tags/digests according to the project's release policy; immutable digests are preferred where release provenance matters.
- Keep development `build:` flows separate from production image-selection semantics when both are supported.
- Multi-stage builds should keep build toolchains and unnecessary artifacts out of the runtime image.

## Runtime behavior

- New long-running services should declare an image/Compose `healthcheck` where supported. Use an actual lightweight check supported by the image and appropriate timing; avoid accepting `running` as proof of health. Coolify Compose reads healthchecks from Compose/image. One-shot bootstrap jobs use completion/failure gates instead. Detailed metric delivery and service-specific diagnostics belong in the owning service runbook, not this universal skill.
- Make restart behavior explicit when process recovery semantics matter.
- Avoid privileged mode, host networking, broad device mounts or writable host paths unless the service contract requires them.
- A privileged **one-shot** bootstrap can be valid when trusted deployment code must prepare host prerequisites and the accepted threat model allows that authority. Keep it non-persistent, narrowly scoped and unavailable to untrusted workloads; do not convert the persistent application into a privileged container for convenience.
- Do not add a second reverse proxy/service manager/control path when the project already has one.
- Prefer behavioral acceptance over incidental metadata. For namespaced/rootless runtimes, numeric UID/GID/group values visible from different namespaces may legitimately differ; prove that the intended process can perform the required operation instead of inventing equality invariants.
