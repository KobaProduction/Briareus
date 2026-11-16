# V2 repository and documentation ownership

## Target source roots

| Target location | Owner |
| --- | --- |
| infrastructure/ | Control Plane UI/backend, private human Rauthy integration, Platform, Resources, external infrastructure |
| hands/ | Autonomous Node/Gateway/Access, isolated local Projects and independently configured MCP modules |
| shared/ | Explicitly reusable narrow contracts, transports and mechanisms |
| docs/ | [Core](core/README.md), [Infrastructure](infrastructure/README.md), [Hands](hands/README.md), [Shared](shared/README.md), [Operations](operations/README.md) |
| scripts/ | Build and quality tools, not deployment ownership |

Every deployable owner retains source, dependency lock, Dockerfile/Compose, health and state/migrations as needed. Hand modules have one catalog directory each and may be deployed in different subsets per Node. Node's Gateway and Access enforce Project/session authority; central Infrastructure never owns Node grants merely because it coordinates management.

## Observed source is not the target

At the V2 documentation revision, **services/** still contains substantial runtime source and Compose definitions; **hands/** and **shared/** also have implementations; the target **infrastructure/** directory is not yet populated. Existing services/ paths and their saved Coolify Base/Compose/Watch configuration are migration inputs, not evidence that the new target packaging is accepted.

Source movement must be qualified by existing imports, actual consumers, generated build inputs, persisted storage and exact approved Development settings. Do not create missing directories or new apps merely to satisfy documentation. The previous Authorization service source remains protected migration inventory, not a future central session authority.

## Development workspace

In the shared Server filesystem use **one Git checkout per repository** under /workspace/projects/briareus and linked worktrees for parallel tasks. In the V2 product, a Project is a logical UUID-bearing entity with **independent private storage on each Node placement**; a Git working directory or worktree inside a Project does not create a new Project or access boundary.

See [canonical source policy](core/source-topology-policy.md), [Git/worktrees](operations/git-and-worktrees.md) and [topology](architecture/infrastructure-hands-shared.md).
