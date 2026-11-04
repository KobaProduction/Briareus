# Briareus contracts / mcp-resources

This leaf owns the `briareus_mcp_resources` module.

Consumers: control-panel-api, gateway.

Its deployment watch is `shared/contracts/mcp-resources/**`. Category directories are not
source packages or broad deployment watches. Service configuration fields live
with their service/capability; dependencies contain no imports from this module.
