# Resources and secret delivery

## Ownership

Node owns its local Project connections, variables and durable secret values.
Infrastructure Resources owns the Team-shared catalog and its source values.
Control Plane UI/API manages bindings through owner interfaces. Rauthy
human credentials/identity keys are a separate authority, not shared
integration resources delivered to Node.

Bindings distinguish Node-local resources from Team/shared/external sources.
Both support the same consuming application use cases without domain imports
of provider SDKs or another owner's database. The source reference identifies
origin/version/scope; it is not a runtime requirement to fetch a credential
from Control Plane before each MCP operation.

A Project binding uses the same logical Project UUID on every Node; Node
UUID + Project UUID distinguishes materialized local values and applied
versions. Shared Project identity is not proof that a value has been
delivered, a grant inherited or a Node authorized to use another placement.

## Local runtime resolution

Before a shared resource is usable, its required value is delivered and
stored durably in the Node database, with the binding/source reference and
applied version. Working MCP operations resolve it locally. Node does not
poll the central catalog or fetch secrets through Control Plane per action.

A lost control connection does not delete the stored value, impose a new
cache TTL or stop use of otherwise valid local resources/grants. Credentials
still obey their actual provider validity; local storage cannot override
provider expiry/revocation. An absent or invalid required value is a typed
unavailable/denied condition, never an empty credential or fabricated success.

Protect stored secret values and restrict resolution to the exact Project/
resource purpose. Metadata/list responses and logs contain references,
versions and status, never tokens/private keys or plaintext secret values.

## Control Plane-driven synchronization

Control Plane initiates delivery and reconciliation. Source rotation,
binding changes and periodic checks compare desired source/binding versions
against Node-reported applied versions. Send changed values through the
existing gRPC or WSS/binary Protobuf management channel; no separate Node
poller or runtime catalog dependency is introduced.

Node validates the target Node/Project/binding and update version, applies
the value atomically to its local durable store and acknowledges operation/
version/status without echoing the value. Reconnect/retry keeps command
identity; duplicates are idempotent and older versions do not overwrite newer
ones. Control Plane reconciles pending differences after connectivity returns.
Connection may physically be Node-initiated; synchronization commands are
still logically initiated by Control Plane.

Disconnected Node uses its last locally applied state. A remote change or
unbind becomes effective there after delivery; do not claim instantaneous
remote invalidation while disconnected. Actual provider-side revocation may
independently make a credential unusable. Session grants and resource-secret
versions remain distinct state and never imply each other's authority.

A Team-source binding is updated from that source; editing a local resource
does not silently detach/change a shared binding. Source selection is explicit.
Standalone local resources require no infrastructure catalog.

## Scope and acceptance

Infrastructure validates human Team/Project access for shared management/
binding. In MVP a member may manage that Project; Node Access independently
decides the session operation/resource under the selected mode: the matching
grant in enforced mode or automatic approval in auto-approved mode. Project
isolation applies in both. A shared token is not a grant
to use Browser/Terminal or full Node control.

Verify initial delivery and local persistence, use without Control Plane,
source updates, periodic/reconnect reconciliation, duplicate/out-of-order
delivery, scope checks and secret-free metadata/logging. Preserve existing
accounts/credentials/storage through qualified migration. Documentation and
source interfaces do not establish accepted live provider behavior.

See [Node storage](node-storage-and-transfer.md),
[identity/access](identity-and-session-access.md) and
[Control Plane API](../control-plane-api.md).
