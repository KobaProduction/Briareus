# Pinned Rauthy protocol and public-route boundary

Rauthy is private infrastructure identity. Native Control Plane UI/API
authentication is handled by Control Plane backend, which owns
provider session/challenge/CSRF/PoW/MFA/OIDC state and validates responses.
The browser does not navigate to hosted Rauthy screens or call arbitrary
provider user/admin APIs.

Derive required protocol routes, methods and provider privileges from the
actual pinned upstream source/configuration. Expose only deliberately
registered OAuth metadata/resource protocol surfaces; a whole provider
namespace or HTML/asset passthrough is not a native login dependency.
Do not invent endpoints or treat a hosted page/redirect as completed login.

Provider cookies and operator credentials remain server-side. UI receives
the intended bounded challenge/authentication result through Control Plane
API, not raw provider management capability. Required MFA/continuations
must complete; unsupported/missing proof is unavailable, not fallback success.

Each module MCP endpoint retains its configured resource/audience contract.
Node Gateway/Access applies local Project/session Cedar authority separately.
Explicit standalone Node may omit OAuth while retaining sessions; identity
failure never silently selects that mode.

Route/source review does not establish accepted deployed privacy or login.
Qualify real behavior in the authorized test/deployment phase and preserve
provider state and approved app scope.

See [human routes](../../docs/services/gateway/rauthy-v0371-public-users.md),
[management privacy](../../docs/services/gateway/rauthy-v0371-public-admin.md)
and [identity/access](../../docs/architecture/identity-and-session-access.md).
