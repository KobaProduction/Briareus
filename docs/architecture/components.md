# V2 component map

This is a **navigation view**, not a second independent policy source.

| Owner | Boundary and reference |
| --- | --- |
| [Infrastructure](../infrastructure/README.md) | Control Plane UI/backend, Rauthy-backed human authority, Teams/Projects, Platform/Resources |
| [Hands/Node](../hands/node/README.md) | Node Gateway, Node Access/Cedar, isolated Projects, local state and execution |
| [MCP module catalog](../hands/modules.md) | Files, Terminal, Web, SVC, Reverse, Infrastructure and other independently packaged modules |
| [Shared](../shared/README.md) | Typed Protobuf/RPC, reusable transport and narrowly shared mechanisms |
| [Operations](../operations/README.md) | Owner workflow, approved Development scope, quality and qualified deployment |

The canonical architecture is [Infrastructure/Hands/Shared](infrastructure-hands-shared.md). See [identity/session rules](identity-and-session-access.md), [session modes](session-access-modes.md), [Node storage](node-storage-and-transfer.md), and [resource delivery](resources-and-secret-sources.md) for technical invariants.

A source directory or documentation page does not assert that V2 runtime migration and acceptance are complete.
