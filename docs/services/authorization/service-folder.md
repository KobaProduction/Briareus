# Retired infrastructure Authorization service

There is no separate infrastructure Authorization service in the target
architecture. Do not implement or deploy a central AgentSession/Cedar/grant
owner or route Node effects through the legacy service.

Node Access exclusively owns local session creation, requests, grants,
decisions, revocation and audit in each Node. Gateway/modules use that Node's
typed decision contracts under its selected enforced/auto-approved mode.
All operational state persists in Node-owned storage; no central runtime
grant or execution database replaces it.

Control Plane backend owns private Rauthy integration and provider state.
Infrastructure owns human users,
Teams/groups, Project relationships and human management scope. Its backend
coordinates scoped Node RPC, records event projections and serves Node-wide
and Project-wide views and explicit refresh. Those projections are not
operational permission or a second authoritative Node state store.

The existing source directory, databases and allowlisted Development app
are migration inventory only. Documentation retirement does not delete or
stop an app, reset a database, move encrypted/provider state or authorize a
live cutover. Owners must qualify replacement contracts, state preservation,
consumer migration and recovery/rollback before retiring runtime artifacts.

See [Control Plane responsibilities](../../control-plane-api.md),
[Node Access](../../hands/node/session-access.md) and
[approved scope](../../operations/BRIAREUS_DEV_ACCESS_SCOPE.md).
