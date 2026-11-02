# Source ownership and coordination

Assigned owners work on disjoint files/modules, preserve peer edits and
coordinate shared contracts through the root owner. A shared package has
one editor and explicit consumers. Do not create a second implementation
or overwrite another owner's work to pass checks.

Backend owns infrastructure human/Project/resource scenarios, Frontend
owns Control Plane UI, Runtime owns Node/Gateway/Access/MCP execution, and
Deployment owns approved infrastructure and qualified rollout. Contract
changes cross those boundaries through typed owner APIs, not database imports.

Progress is reported in chat; machine diagnostics belong in ignored
artifacts/. Do not create local task/backlog/report Markdown. Assignment
lanes do not authorize spawning or messaging agents without the required
user/applicable instructions.

Complete all source owners before separately user-authorized tests/fixtures.
Scoped static diagnostics and batched native checks are allowed. Validate
coherent owned batches locally before ordinary push/approved Dev rollout;
preserve hooks/protections and avoid per-action publication or repeated CI.

Only the exact [approved Dev scope](BRIAREUS_DEV_ACCESS_SCOPE.md) is available
for infrastructure work. No unrelated browsing, plaintext secrets, Production,
new resources, reset or global restart follows from source coordination.

See [workflow](implementation-workflow.md) and
[quality policy](../../scripts/quality/README.md).
