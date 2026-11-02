# Identity resource intent and session effect access

Control Plane backend owns the supported private Rauthy exchange, original
resource intent, provider session, PKCE/state/nonce and token validation.
The UI exchanges typed authentication requests/results with backend RPC
over WSS. No separate infrastructure Authorization service participates.

Each separately exposed module MCP endpoint keeps its configured resource/
audience. Preserve exact intent through the provider exchange; callbacks,
headers and later tool parameters cannot replace it or choose an arbitrary
issuer/client/URL. A rejected resource is not an unscoped successful grant.

Connected resource verification follows configured issuer/signature/audience/
expiry requirements. Explicit standalone Node may omit OAuth without inventing
human identity. Required identity failure does not silently switch modes.

Node Access separately checks the local Node/Project AgentSession and exact
action/resource under the selected access mode: Cedar grants in enforced
mode or automatic approval of valid in-Project actions in auto-approved
mode. Project isolation applies in both. An identity token, provider account capability
listing or another module audience is not permission for a protected effect.
Session/grant state remains autonomous Node storage.

See [authentication](native-login.md),
[identity/access](../../architecture/identity-and-session-access.md) and
[session access](../../hands/node/session-access.md).
