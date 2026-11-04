# Briareus mcp client

This leaf owns the `briareus_mcp_client` module.

Consumers: control-panel-api, analysis.

Its deployment watch is `shared/mcp_client/**`. Category directories are not
source packages or broad deployment watches. Service configuration fields live
with their service/capability; dependencies contain no imports from this module.
