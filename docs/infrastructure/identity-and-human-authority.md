# Infrastructure — identity, administrator and human access policy

**Status: binding V2 owner policy.**

Binding V2 human/Control Plane identity rules. Rauthy is the identity authority; the Control Plane backend owns its private integration and human management scenarios. Node Access is a separate owner.

See [identity and session access](../architecture/identity-and-session-access.md), [backend contract](../control-plane-api.md), and [native login](../services/api/native-login.md).

**IDENTITY/AUTH DESIGN:** docs/architecture/identity-and-session-access.md (Rauthy + Cedar).

**AUTHENTICATION:** `Control Plane UI → Control Plane backend → private Rauthy`. Backend owns the pinned private provider protocol, sessions/challenges/CSRF/PoW/MFA/OIDC state and protected administration credentials. Rauthy exclusively stores/verifies human credentials and issues/revokes identity tokens. UI owns all login/MFA/recovery screens and uses backend RPC over WSS. Provider state/keys never reach UI or Node; passwords/MFA secrets are never persisted/logged by Briareus. No separate infrastructure Authorization service or second identity signer/password verifier. Missing required provider evidence fails closed.

**INITIAL ADMINISTRATOR:** Rauthy creates its initial administrator during empty-provider initialization; sign-in uses UI → backend → private Rauthy. No registration link in logs or first-visitor role assignment. Preserve provider state; no log password scraping or reinitialization because a local projection is absent.

**ACCESS OWNERSHIP:** Infrastructure/Rauthy owns human identity/groups/rights; backend checks human Node-wide management scope and Project-wide membership before queries/commands. An MVP Project member may manage/approve within that Project, not the entire Node or unrelated Projects. Node Access exclusively owns local sessions, requests, grants, Cedar and audit. Backend stores event projections for Node-wide/Project-wide views and refreshes through paginated active-request RPC and revision/cursor reconciliation; projections grant nothing. Human-appointed approver sessions act only in their Node/scope, never appoint approvers, self-approve the same requesting session or gain upstream rights. Metadata is untrusted.
