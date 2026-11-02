# Native Briareus authentication

## Service contract

```text
Control Plane UI --RPC/WSS--> Control Plane backend --> private Rauthy
Control Plane UI <--RPC/WSS-- Control Plane backend <-- Rauthy-issued token
```

Control Plane UI owns every user-facing sign-in, MFA, recovery and session
screen. The browser submits only to the Briareus Control Plane backend. It never
opens a Rauthy login page or directly calls a Rauthy API.

Control Plane backend owns the complete authentication use case and its private
Rauthy adapter. It starts and continues the supported provider session,
handles password/MFA/recovery challenges, validates the provider response
and returns the Rauthy-issued token through its browser RPC contract. Refresh,
logout and recovery use the same ownership boundary.

Rauthy exclusively owns accounts, stored credentials, password/MFA checks,
OAuth/OIDC identity sessions, signing keys and identity-token issuance,
refresh and revocation. The backend uses the version-pinned provider
protocol rather than implementing another password verifier or token issuer.

## Initial administrator

Rauthy creates the initial administrator during empty-provider initialization.
The operator uses that account in the native Briareus sign-in screen. The backend
does not create an anonymous first-admin registration flow,
print a registration link or derive admin privileges from request ordering.
Normal restarts reuse provider state. Missing Platform operator state cannot
trigger provider initialization or reset. Briareus services do not read the
initial provider password from logs.

## Provider protocol and private state

Control Plane backend retains the Rauthy provider cookie, CSRF/PoW state, OAuth
state, PKCE verifier, nonce and MFA continuation state server-side. Only
browser-safe challenge data and the intended authentication result cross
the backend/browser boundary. Provider operator credentials, private signing
material and provider cookies do not reach the browser or Node.
User-entered passwords and MFA secrets are never persisted or logged by
Briareus. Provider responses and error messages must not echo these inputs.

Each continuation is bound to its original transaction and permitted stage.
Completion/cancellation must be atomic and idempotent where appropriate;
replayed, expired, mismatched or already consumed state cannot authenticate
another request. Unsupported continuation or missing provider evidence
returns a typed unavailable/error result and never a fabricated token.

## Browser and RPC boundaries

The browser-facing authentication contract consists of typed RPC service
methods and Protobuf messages, carried over WSS to the backend. Internal
first-party services use the same RPC architecture through native gRPC or
WSS adapters. Private Rauthy integration retains its pinned native provider
protocol; it is not replaced with an invented gRPC provider interface.
There is no separate infrastructure Authorization hop or service.
Methods, DTOs and errors are versioned together by their owners. A documented
flow is a requirement, not proof that a particular endpoint is deployed.

Browser requests have bounded input sizes and deadlines, validated origin
and content type, and no caller-selected provider URL/client/redirect.
Private provider calls use the configured protected transport and exact
provider endpoints. The backend returns challenges, results and errors without manufacturing
identity, permission or authentication success.

## Identity and access

Successful login yields the provider-issued token. It does not create a
Project membership, AgentSession grant, Files permit or approval privilege.
Infrastructure owns the current human User/Team/Project relationships and
management scope. Node Access exclusively owns AgentSessions, requests,
Cedar policy, operational grants and effect decisions in the owning Node.
Enforced mode checks the applicable grant; auto-approved mode automatically
admits valid in-Project actions. Both require the active session and Project
isolation. Human login grants no Node session or approval authority.

## Acceptance

Verify a real browser sign-in through backend RPC into private Rauthy,
challenge continuation, returned provider token, refresh,
logout and recovery. Verify missing/invalid state and unavailable provider
fail without token issuance. Browser navigation and network requests must
show no direct Rauthy login or API access. A health probe, mocked provider
or source-only check does not establish complete product acceptance.

See [Identity and access](../../architecture/identity-and-session-access.md).
