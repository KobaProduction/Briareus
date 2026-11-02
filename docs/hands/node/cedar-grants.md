# Cedar integration for Node session grants

Cedar is embedded in Node Access to evaluate session operation/resource
access and current approver authority in enforced mode. It does not manage human groups,
administrator roles or provider credentials. Human identity and management
scope belong to infrastructure. There is no infrastructure Authorization
service in the target architecture; all session authorization lives in Node.

In auto-approved mode Node Access automatically approves valid sessions and
their in-Project actions without a manual Cedar grant. Gateway/modules use
the same decision contract. Project isolation, session lifecycle and resource/
command validity are unconditional; the switch grants no approver/management
authority. See [mode contract](../../architecture/session-access-modes.md).

Node Access loads only its own durable session/grant/request/revision state
through SQLite/PostgreSQL ports. Evaluate the exact Node, Project, session,
action and canonical owner resource. Unknown or unavailable required inputs
deny new protected work. A tool/catalog entry or selector is not authority.

The explicit Node-wide common directory has read/write access for all local
Projects without individual grants/per-entry restrictions in either mode.
It is a canonical shared resource, not a private Project path; bind actions
to the active session/Node for observation/audit and prevent path/link escape
to private data. This shared-data rule does not grant management or permit
editing read-only system-tool installations.

Only human/operator management appoints an approver session. Such a session
can grant operational access within its Node/scope, but cannot appoint
another approver, delegate approval authority, approve its requesting
session or reach privileged Control Plane management. Human and session
decision adapters invoke the same typed application use cases.

Approve only the requested action/resource scope or a subset. Expanding
scope is a new explicit request/authorized decision, not a hidden payload
flag. Decisions are versioned, idempotent and audited.

In enforced mode each grant expires independently. Check validity on new-operation admission;
admitted/started work may finish after expiry. Do not stop the session or
revoke unrelated grants when one elapses. Activity refreshes idle tracking
only. Explicit stop/cancel/revoke is a distinct command.

Keep policy/domain invariants inside Node Access rather than copying them
into every MCP module or transport adapter. Shared packages hold narrow
contracts/runtime plumbing with explicit consumers. Source work precedes
the separately authorized aggregate test phase; no gate weakening or
duplicate production implementation is used to satisfy checks.

See [session contract](../../hands/node/session-access.md) and
[identity/access](../../architecture/identity-and-session-access.md).
