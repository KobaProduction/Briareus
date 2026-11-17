# MCP Strategy

Move repetitive, environment-heavy, error-prone or privileged operations into specialized MCP tools as early as practical.

A good MCP capability encapsulates dependency setup, credentials, environment, command syntax, validation, safe defaults and structured output.

## Preference
When provided by the project:
1. specialized project MCP;
2. structured connector/API;
3. controlled runner/shell;
4. manual user action only when physically/privileged necessary.

## Good MCP candidates
Operations repeated across agents/sessions, easy to invoke incorrectly, dependency-heavy, permission-sensitive, naturally structured or useful to audit centrally.

Examples:
- Git mutation/review;
- reverse database operations;
- immutable artifacts;
- HTTP/download/stream capture;
- CI/build orchestration;
- inventory/evidence ingestion.

## Tool contract
Prefer:
- typed parameters;
- dry-run for risky mutation;
- expected-state guards;
- deterministic outputs;
- provenance/identity reporting;
- capability/permission introspection;
- separate review and mutation surfaces where useful.

## Agent rule
If a specialized MCP exists, use it instead of rebuilding/installing the same workflow manually.

If capability is missing, report the gap. Do not silently bypass the project’s primary tool surface unless allowed.

For the universal AI Agent Workflow library, the configured GitHub MCP is the
authoritative live read surface. If a required document or connector is
unavailable, stop dependent actions under Account/Project rules; do not
substitute local clones, previews or unauthorized transports. An agent cannot
install or authorize an MCP connection on the user's behalf.

Concrete endpoints, installation IDs, credentials and transient infrastructure values belong in infrastructure authority, not the account prompt. Stable role aliases may be documented when they define an agent workflow contract.

## GitHub identity separation

Where the GitHub integration exposes both standard identities, keep mutation and approval separate:
- writer alias `koba-ai-agent`: repository writes, working branches, commits, issues, pull requests and requested revisions;
- reviewer alias `koba-ai-reviewer`: independent review and final pull-request merge.

The writer does not merge its own PR. The reviewer does not modify the implementation under review. Reserved/default branch protection is treated as a workflow boundary, not bypassed through another transport.


## Web / HTTP routing

For ordinary web research, documentation lookup and public information, prefer the built-in browser/search path.

Use MCP cURL when:
- browser/search cannot retrieve the needed response;
- direct HTTP semantics are required;
- a file/download must be streamed into an artifact-capable path;
- a long-lived/chunked/streaming response must be captured;
- browser/search limitations block the task.

Do not force MCP cURL for normal browsing when the built-in browser/search path is sufficient.

Do not specify a cURL preset unless the task explicitly requires a non-default request profile.
