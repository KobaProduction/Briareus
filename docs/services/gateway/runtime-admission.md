# Node Gateway admission

Node includes Gateway and Node Access/Cedar. Expose separate MCP endpoints
for configured Files, Browser, Terminal and other modules; direct and
Control Plane-proxied ingress preserve Node/module selection. Do not merge
all catalogs or assume every Node deploys the same module set.

Gateway performs connection/tool admission through Node Access; each module
resolves the canonical Project resource and checks the exact effect against
that same Node authority. Gateway owns transport, not human roles, module
business parsing or a duplicate policy engine.

Node UUID + common Project UUID selects local session/workspace/resource
state. Caller paths/headers and routing labels cannot invent a Project or
grant. One session may use approved operations through several same-Node
endpoints; opening a connection does not grant tool access.

Configured connected identity/audience requirements apply to MCP traffic.
Explicit standalone mode can omit OAuth while retaining sessions/Cedar;
an identity-service outage never enables anonymous fallback. Node execution
does not require a synchronous central grant/database request per effect.

Full private management supports native gRPC and WSS/binary Protobuf with
shared use cases, validators and idempotent command/result/event contracts.
It is distinct from restricted MCP calls. Preserve bidirectional framing,
backpressure/cancellation, exact scope and command identity across reconnect.
Either side may initiate connectivity without changing authority.

Node Access supports enforced and auto-approved modes. The latter
automatically approves valid sessions and all their in-Project actions
without manual grants; both modes preserve Project isolation, session
lifecycle and valid command/resource binding. Only trusted full management
changes mode; see [mode contract](../../architecture/session-access-modes.md).

In enforced mode check grant validity when admitting new work. Expired grants block new
operations but do not cancel admitted work, stop the session or revoke
unrelated grants. Explicit stop/cancel follows its own authority/lifecycle.
Transport failure is not evidence that an operation did not commit.

Human auth screens stay in Control Plane UI; Control Plane backend
privately integrates Rauthy. Gateway exposes only the deliberately configured
protocol/resource routes, never a generic provider/admin proxy.

See [management/MCP contract](node-management-and-mcp.md),
[session access](../../hands/node/session-access.md) and
[topology](../../architecture/infrastructure-hands-shared.md).
