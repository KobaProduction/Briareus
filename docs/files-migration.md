# Project Files data transfer and migration

Move existing files into a Node/Project workspace through an explicitly
scoped verified operation. Preserve sources, checksums/manifests and
recovery information until destination content and ownership are confirmed.
Existing volumes are not empty because a runtime expects another path.

Identify destination Node UUID, Project UUID and Project-relative path.
Each Project workspace is isolated and shared only by its own modules.
Do not import unrelated Projects into a global workspace or expose all
Projects to a file-manager workload.

Copy and verify destination content before separately authorized source
deletion. Partial/unconfirmed transfer retains the source. Preserve
operation identity across retry, reconcile uncertainty and qualify rollback.
Provider-native databases require their owner's transfer contract.

One interface covers Projects on the same Node and cross-Node transfer.
Files carry no session grant or approval authority. Documentation does not
establish a completed live migration.

See [Files](file-service.md) and
[Node storage/transfer](architecture/node-storage-and-transfer.md).
