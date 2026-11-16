# Node — Gateway, local Projects and Node Access

A Node owns the **entire local execution boundary**, including independently configured MCP modules, private Project workspaces, Node-wide common files, Node-local resource values, AgentSessions, requests/grants, audit/revocation and durable execution state. Its central attachment is optional: an explicitly standalone Node operates without Control Plane, Teams, users or Rauthy.

Node Gateway routes individually configured MCP module endpoints and performs **coarse** admission through Node Access. Each module resolves the actual canonical Project resource and requests an exact-effect decision from the same Node Access application service; do not duplicate Cedar policy in adapters.

Node Access owns Cedar grants and the **enforced / auto-approved** switch. Auto-approved mode confirms valid sessions and in-Project operations without individual manual grants; it never bypasses session binding, data isolation, command/resource validation, human authority or audit. In enforced mode grants have distinct deadlines and scopes, and expiry blocks only new work; already admitted operations may finish.

Full private Node management is separate from ordinary MCP session APIs. Management supports **native gRPC and WSS with binary Protobuf**, one versioned contract and shared application use cases over persistent bidirectional commands/results/events. Standalone mode is explicit, never a fallback after an auth outage.

Detailed contracts: [binding authority](../node-access-policy.md), [session lifecycle](session-access.md), [Cedar](cedar-grants.md), [Files read admission](files-read-access.md), [project/storage rules](../storage-policy.md), [Node control-channel protocol](../../services/gateway/node-management-and-mcp.md).

These are **target requirements**, not confirmation that all services have completed their source migration or are deployed and accepted.
