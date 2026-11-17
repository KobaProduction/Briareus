# Briareus V1 MCP — recurring failures and prevention

These guides describe **Briareus-specific MCP integration failures**, not
generic shell, Git, testing or deployment methodology. The independent
AI Agent Workflow Skills own those universal methods. Briareus must remain
usable even when the AI Agent Workflow plugin is not installed.

## Select the failed layer before retrying

| Symptom | Briareus-specific guide | Evidence to inspect |
| --- | --- | --- |
| Duplicate checkout, wrong workspace, Terminal job disconnect, exit 137 | [Server / jobs](server.md) | Existing checkout remote, job state, exit/cgroup data |
| Wrong branch, unexpected PR/MR, denied provider write | [GitHub / GitLab](source-control.md) | Selected account, effective policy, target branch and actual rejection |
| ChatGPT internal error, token refresh or 401 | [OAuth / client](authentication.md) | Whether request reached Gateway; sanitized issuer failure |
| Unregistered Hands, Valkey WARN flood, stale browser references | [Discovery / browser](runtime.md) | Affected service set, lease and CDP state |
| Coolify 401/403, missing logs, unreadable variable, queued deploy | [Coolify](coolify.md) | Required grant, exact resource, deploy UUID and healthy state |

Before a potentially destructive or hard-to-reverse action, select the
appropriate guide and read its prevention checks *before* calling the tool.
Do not load all guides for every ordinary read-only call.

On error, follow client → issuer → Gateway → discovery → Hand → upstream
provider / Server job in that order. A private Hand responding does not prove ChatGPT
OAuth works; a running container does not prove its MCP is authorized.
Collect nonsecret operation name, target class, UTC time and error category
before selecting recovery. Recheck current deployment and open issue state;
historical incidents do **not** prove the same cause exists now.

Never expose tokens, credentials, session identifiers or unredacted sensitive
runtime logs. Never blindly replay a possibly committed write, delete a
workspace or browser profile, restart every Hand, or loosen OAuth protections
to fix a generic error.

The [Hands owner index](../README.md) routes to authoritative capability
contracts. Source modifications follow [AGENTS.md](../../../AGENTS.md) and
[testing levels](../../operations/testing.md). Each diagnosis guide links to
its **single owner**; do not maintain a second copy of that owner's rules.
