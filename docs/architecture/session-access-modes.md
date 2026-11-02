# Node session access modes

## Independent layers

Infrastructure supplies human identity, users/groups/Teams, collaboration
and authorized Project management. Node can start, host local Projects,
manage its MCP modules and execute work without the Panel or infrastructure
services. An agent is an external MCP client using Node-local sessions;
Node does not need to establish a persistent unique agent identity.

Node has two explicit session-access modes: `enforced` and `auto-approved`.
These are semantic contract names, not claims about implemented configuration
keys. The default is `enforced`. The mode is Node-owned configuration managed
through trusted operator/full management, never an ordinary MCP argument.
It works with or without a Panel. Standalone/connected deployment and
session-access mode are independent choices.

## Enforced

Creating a session records its Node/Project and review metadata but grants
no protected operation. Requests wait for a Project user's decision through
Control Plane or an authorized local approver session. Node Access/Cedar
checks applicable grants, scope and hard deadlines before each new effect.
Expired grants block new work; admitted and started work may finish.

## Auto-approved

The switch automatically approves every valid new session and every action
of an active session within its own Project. There is no manual review,
pending approval wait or requirement to acquire individual operational
grants. Node Access returns the automatic approval through the same typed
admission/effect contract; Gateway and MCP modules do not maintain separate
switches or continue denying work because a manual Cedar grant is missing.
This covers existing active sessions as well as newly created sessions.

Sessions still exist and identify the source of actions. Creation records
Node UUID, Project UUID, session UUID and metadata and returns a ready
session. Requests handled in this mode record automatic approval rather
than inventing a human approver or a human decision. Audit records the mode
and automatic source of an operation's admission.

The switch approves ordinary session operations only. It does not appoint
approver sessions, delegate approval authority or expose full Node/Panel
management to an MCP caller. Only trusted full management changes the mode.
Configured infrastructure login, Project membership and MCP transport
identity remain their own layer; automatic session approval is not a
replacement human identity or an authentication-outage fallback.

## Project isolation is unconditional

Both modes require a real active session bound to an existing Node/Project,
valid commands and actual module/resource availability. A stopped session
is not revived by the switch. Sessions cannot read or mutate another
Project's workspace, terminal home, browser profile, credentials or private
runtime storage. Canonical resource binding, filesystem/process isolation,
path/symlink boundaries and protocol/data-integrity validation always apply.

Automatic approval never turns an ordinary file/process action into a
cross-Project operation. Transfer remains a separate explicit interface
with source/destination Node and Project scope, including on the same Node.
No ordinary MCP path can escape its Project even when approval is automatic.

## Mode changes and grant lifetime

Node's explicitly common directory is a separate deliberately shared
namespace, readable/writable by all its Projects without per-entry or
individual-grant restrictions in either mode. It never exposes another
Project's private root, home/profile/credentials or module-private store.
Sessions identify common-storage actions for observation/audit. This shared
data capability is distinct from read-only Node-managed system toolchains
and from private cross-Project transfer. See
[storage contract](node-storage-and-transfer.md#node-wide-common-directory).

Changing mode is an explicit, recorded management decision. Returning to
`enforced` requires valid explicit grants for new protected work; automatic
approvals do not become permanent grants or approver authority. Existing
explicit grants retain their own scope, deadline and revocation state.
Activity or mode changes do not extend or resurrect them. Work already
admitted and started may finish; explicit stop/cancel remains separate.

A disconnected Panel, failed identity check, unavailable database or missing
policy never changes the selected mode. Automatic approval uses configured
Node policy, not a fallback after a failed check. Node-local durable state
and mode survive normal restart without requiring central storage.

## Acceptance

After the separately authorized test phase begins, verify both modes with
direct and panel-proxied ingress and both management transports. Include
automatic session readiness/actions, transition back to explicit grants,
stopped sessions, audit and mandatory Project isolation in both modes.
This document specifies behavior; it does not establish implementation or
authorize changing a running deployment's mode.

See [identity/session access](identity-and-session-access.md),
[topology](infrastructure-hands-shared.md) and
[storage and transfer](node-storage-and-transfer.md).
