# Briareus telemetry

This leaf owns the `briareus_telemetry` module.

Consumers: control-panel-api, gateway, github, gitlab, web, server, analysis, ghidra, observability.

Its deployment watch is `shared/telemetry/**`. Category directories are not
source packages or broad deployment watches. Service configuration fields live
with their service/capability; dependencies contain no imports from this module.

`DEPLOYMENT_ENVIRONMENT` is required and identifies the deployment in
`deployment.environment.name`. Use an operator-assigned name of up to 63 characters:
lowercase letters, digits, dots, underscores and hyphens, starting with a letter or digit.

MCP observability distinguishes application failures from rejected tool calls.
An invalid request (for example a workspace-escaping `cwd`, an unrecognized
account alias, or an unmatched Serena replacement) is still an MCP tool error
to the agent and is retained as an `error` in the invocation audit. Explicitly
classified FastMCP caller rejections log `WARNING` and increment
`mcp.tool.rejections` instead of `mcp.tool.errors`. The regular call count and
duration metrics still include them. Genuine service, network, and process
failures remain `ERROR` and increment `mcp.tool.errors`. Rejections are marked
with `mcp.outcome=caller_rejected` in metric attributes; this classification
never changes tool authorization, path checks, or the MCP `is_error` result.
