# Briareus authentication and MCP OAuth

## Browser authentication

All sign-in, MFA and recovery screens belong to Briareus Control Plane UI.

```text
Control Plane UI --RPC/WSS--> Control Plane backend --> private Rauthy
Control Plane UI <--RPC/WSS-- Control Plane backend <-- Rauthy-issued token
```

Rauthy stores credentials, verifies passwords/MFA, issues and revokes identity
tokens and owns signing keys. Control Plane backend owns the provider protocol,
server-side session/challenge state and private Rauthy adapter. There is no
separate infrastructure Authorization service. The backend uses private
provider calls and never signs replacement identity tokens. The browser receives
the resulting token through Briareus and never opens or calls Rauthy.
Passwords, MFA secrets and provider operator credentials are never persisted
or logged by the UI or backend; private provider administration credentials
remain protected server-side.

## MCP identity and permissions

Rauthy is the infrastructure identity-token issuer. Control Plane backend
is its private integration owner and checks human Node/Project management
authority. Node Access owns Node-local sessions, operational grants, approvals,
revocation and Cedar policy. An agent uses sessions through module MCP endpoints;
it never requests operational grants from Rauthy.

A Node works without the Panel or Rauthy in explicit standalone deployment.
Connected transport identity and Node session-access mode are independent.
In enforced mode, Gateway/module effects require current Node-local grants;
in auto-approved mode, valid sessions and their in-Project actions are
automatically approved. Project isolation is mandatory in both modes. See
[session-access modes](architecture/session-access-modes.md).

Each MCP resource has its own exact resource/audience contract. OAuth client
registration, discovery, callbacks and resource audiences must match supported
provider configuration; this document does not assert deployed URLs or DCR
availability. Provider-hosted login pages are not a Briareus user flow.

Human identity sessions, AgentSessions and execution sessions have independent
lifecycles. GitHub/GitLab and other integration accounts are resource connections,
not Briareus human identity providers.

See [Identity and access](architecture/identity-and-session-access.md)
and [Authorization and access](architecture/authorization-access.md).
