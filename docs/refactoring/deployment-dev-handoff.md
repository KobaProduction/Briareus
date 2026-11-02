# Development integration and publication

Source owners coordinate stable identity, Project/Node, resource-delivery
and session contracts before crossing implementation boundaries. Shared
packages have one editor and explicit consumers; preserve peer changes.

Complete all source owners before separately user-authorized tests.
Work mainly locally; validate affected runtime/lint/type/test/hook behavior
against a coherent proposed/outgoing batch before publication. Do not push
each extraction, repeat unchanged CI or include unverified neighboring work.

Agents may publish within their task and approved Dev scope without approval
for every ordinary push. main is Development where repository protections
allow; otherwise use the required branch/PR path. Preserve hooks/checks and
validate the actual outgoing revision in an isolated checkout when needed.

Verify saved deployment Base/Compose/Watch and independent module lifecycle.
Source target paths are not actual deployment proof. Watch only owning
source/real shared consumers; avoid global invalidation and all-app restarts.

Use only [approved Development scope](../operations/BRIAREUS_DEV_ACCESS_SCOPE.md).
No Production, unrelated inventories, plaintext secret inspection, new app
identity or data reset follows from source/architecture work. Preserve
provider keys/accounts, owner databases, Node state/workspaces and qualified
rollback. Health/images are not accepted login or protected operations.

See [requirements](../architecture/engineering-requirements.md),
[topology](../architecture/infrastructure-hands-shared.md) and
[quality policy](../../scripts/quality/README.md).
