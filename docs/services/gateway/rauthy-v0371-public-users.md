# Rauthy human-flow route boundary

Human sign-in, MFA, recovery and account scenarios are native Control Plane
screens. UI calls Control Plane API; authentication/provider continuations
are owned by Control Plane backend using pinned private Rauthy APIs.
Node contains no Rauthy human-flow implementation.

Do not expose a whole provider user namespace or hosted login UI merely to
make a browser flow work. Classify each required protocol route/method from
the pinned upstream contract and configured OAuth resource registration.
Source/version review does not establish deployed privacy or login acceptance.

Provider user/session/challenge state and privileged credentials remain
server-side. UI receives only the intended bounded challenge/result through
the Briareus API. Do not forward arbitrary caller URLs, role claims, provider
cookies or internal API keys as authority.

MCP OAuth metadata/token protocol routes, where configured, are distinct
from hosted human screens and private user administration. Each module
retains its exact audience; direct/proxied ingress does not invent one.
Explicit standalone Node may omit OAuth while retaining local sessions/Cedar.

Verify actual native workflows and deliberate route exposure in the authorized
test/deployment phase. Preserve provider state and approved infrastructure
scope; no generic public passthrough or secret inspection is implied.

See [identity/access](../../architecture/identity-and-session-access.md) and
[authentication](../api/native-login.md).
