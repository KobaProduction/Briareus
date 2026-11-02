# Infrastructure module integration

Bind the module's real tool catalog and canonical Project resources to the
Node runtime without changing its external MCP schema speculatively.
Own source/build/Compose/dependencies independently; reuse only focused
shared contracts/capabilities with explicit consumers.

Node Gateway routes the separate module MCP endpoint. The module requests
exact operation/resource decisions from Node Access/Cedar; it does not
duplicate human IAM or depend on central grant/database calls per effect.
Explicit deployment mode controls OAuth independently of the Node
session-access switch. Enforced mode requires Cedar grants; auto-approved
mode confirms valid sessions and all in-Project actions without manual
grants. Both preserve session lifecycle and mandatory Project isolation.
Use the Node Access decision contract rather than module-specific switches.
See [mode contract](../../architecture/session-access-modes.md).

Project runtime/filesystem isolation is required. Local resources and
delivered shared secrets resolve from Node storage. New sessions inherit
nothing; in enforced mode expiry blocks new work while admitted work finishes.

Preserve existing data and qualify module/source/deployment cutover and
rollback. Health, copied source and registered diagnostics alone are not
accepted protected operations. Test/fixture work waits until every source
owner finishes and the user authorizes the aggregate phase.

See [module contract](README.md) and
[workflow](../../operations/implementation-workflow.md).
