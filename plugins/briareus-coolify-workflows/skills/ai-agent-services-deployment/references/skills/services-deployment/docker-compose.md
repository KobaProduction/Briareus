# Docker Compose Packaging

Load when editing generic Docker Compose. The base `docker-compose.yaml` must work independently of Coolify; `docker-compose.coolify.yaml` adds orchestrator-specific handling only after verified composition. All new standard filenames use four-letter `.yaml`. For runtime, build, bootstrap and basic healthcheck decisions load `deployment-runtime.md`. If Coolify parses Compose, load `coolify-compose.md`.

## Ownership

- Follow the repository's established orchestrator first. Do not introduce Compose where Kubernetes, Nomad, managed deployment templates or another owner is already authoritative.
- Use Compose when the project already uses it or when one reproducible multi-container definition is the natural local/service contract.
- Keep environment-specific hosts, registry coordinates, secrets and deployment topology in project/local context.

## Coolify parser gate

If Coolify parses or deploys the Compose resource, also load `coolify-compose.md` before editing the manifest. Generic Compose validity does not prove that Coolify will materialize required variables, generated domains, shared references or managed file mounts correctly.

## Compose files

- Preserve established working filenames unless their migration is approved. New standardized deployments use `docker-compose.yaml` and `docker-compose.coolify.yaml`; `.yaml` has four letters, not `.yml`.
- Define services, networks and persistent volumes declaratively when they are part of the reproducible runtime topology.
- Use named volumes for durable container-managed data when host-path ownership is not required.
- Use explicit networks only when topology/isolation requires them; do not add decorative networks.
- Parameterize environment-dependent values through the project's configuration contract instead of hard-coding production values.

## Contract dimensions

Do not collapse these different statements:

- **one deployment entrypoint** — one Compose manifest/resource is how the stack is deployed;
- **one service** — the manifest defines one Compose service;
- **one running container** — steady state has one long-running container;
- **one host runtime** — no additional host daemon/service exists.

A requirement for one Compose entrypoint does not imply one service. A one-shot bootstrap/helper may coexist with one persistent application service in the same manifest when that is the accepted lifecycle.

State these dimensions explicitly before refactoring topology. Do not introduce a second deployment resource merely because one helper needs a different privilege/lifecycle profile.

## Environment and secrets

- Do not commit real `.env` files or plaintext secrets.
- A tracked `.env.example`/template may document required variable names and safe example values when that is the project's convention.
- Secret values should come from the declared secret/provider/runtime surface rather than being embedded in Compose, Dockerfile layers or image metadata.
- Validate required runtime variables explicitly when missing values would produce an unsafe or misleading deployment.

## Operations

Use the project's supported Compose/runner commands. Typical Compose operations are:

```text
docker compose up -d
docker compose down
docker compose logs -f <service>
docker compose pull
docker compose up -d --remove-orphans
```

These are examples, not commands to emit blindly. Human-operated commands still require `../terminal-operations.md` and the active project/local execution contract.

## Validation

Before calling a container change ready, verify the level relevant to the change:

- manifest/config parses;
- image builds when build logic changed;
- declared mounts/networks/env resolve as intended;
- service starts under the real orchestrator/runtime;
- health/readiness and consumer-facing behavior work from the intended surface;
- helper/bootstrap behavior is validated on both first and repeat deployment when it is part of the lifecycle;
- representation checks (owners/groups/generated paths) are tied to an explicit platform guarantee or backed by a real consumer operation;
- rollback/redeployment remains possible for production-facing changes.
