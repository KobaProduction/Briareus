# Implementation ownership and delivery workflow

## Requirements

Implement [topology](../architecture/infrastructure-hands-shared.md),
[identity/session access](../architecture/identity-and-session-access.md),
[storage/transfer](../architecture/node-storage-and-transfer.md) and
[resource delivery](../architecture/resources-and-secret-sources.md).
These contracts describe required behavior, not deployed completion.

## Ownership

- Backend owns private Rauthy integration, Control Plane management coordination, event projections,
  Node-wide/Project-wide human access and central domain/resource scenarios.
  No separate infrastructure Authorization service or Node grant database
  is part of this owner; all session authority belongs to Runtime's Node Access.
- Frontend owns Control Plane UI, native sign-in/MFA/recovery, management and
  session-request review using verified owner responses.
- Runtime owns Node/Gateway, local Projects, Node Access/Cedar sessions/grants,
  per-module MCP endpoints, container lifecycle, autonomous storage and workspace
  isolation. Node approver sessions remain local to their Node/scope.
- Deployment owns approved infrastructure packaging and qualified Dev rollout,
  provider/storage/transport configuration and data-preserving recovery.

Shared contracts have one editor and explicit consumers. Assigned agents own
disjoint files, coordinate contract changes and preserve peer edits. No new
local task/backlog/report Markdown; progress belongs in chat and machine
diagnostics in ignored artifacts/. Ownership lanes do not authorize spawning
or messaging agents outside the current user's instructions.

## Source phase

Remove incompatible legacy implementations, obsolete first-party compatibility
paths and their exclusive obsolete tests instead of maintaining them through
another override/fallback layer. Preserve useful mechanisms and actual
data/runtime invariants. A legacy test does not require retaining rejected
architecture. Classify tests by the invariant they assert: retain applicable
coverage and remove tests exclusively requiring the deleted/incompatible
contract. Never delete a test merely because it exposes a current defect.
No broad frontend refactor is part of this cleanup; limit UI changes to
necessary contract adaptation.

Finish source across all owners before writing/adapting/running new or
retained tests and fixtures. Deletion of proven obsolete legacy tests is
part of the authorized source cleanup. Scoped static diagnostics and batched native/runtime checks are
allowed; no diagnostic-test or per-block-acceptance exception. Verify real
consumer paths and report unsupported-host/dependency failures accurately.

## Authorized test phase

Begin only after every source owner finishes and the user separately
authorizes testing. Adapt tests/fixtures, exercise actual behavior and
consumer boundaries, and perform aggregate acceptance. Do not weaken
hooks, types, complexity gates or required protections. Successful unchanged
checks are not repeated without a concrete reason.

## Batched publication

Work primarily locally, accumulate a coherent owned block and validate
affected runtime, linters/types, tests and mandatory hooks against the exact
proposed/outgoing revision. Then agents may publish within the task/approved
Dev scope without approval for every push. Avoid tiny publication steps,
repeated unchanged CI and unverified peer source. Use an isolated validation
checkout when needed instead of stashing/resetting others' work.

Verify saved Base/Compose/Watch settings, actual changed-module behavior and
independent lifecycle/recovery. Shared changes affect only real consumers.
No source/health-only evidence establishes accepted login, grants, workspace
isolation, provider actions or transport. Preserve data and qualified rollback.

## Infrastructure boundary

Only the exact approved [Development scope](BRIAREUS_DEV_ACCESS_SCOPE.md)
is available for runtime operations. No Production, other tenants, global
resource browsing, plaintext secrets, new app identities or speculative
data resets are implied. Preserve existing credentials, volumes and public
contracts through an independently qualified cutover.
