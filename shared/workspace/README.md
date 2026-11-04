# Briareus workspace

This leaf owns the `briareus_workspace` module.

Consumers: control-panel-api, web, server, analysis.

Its deployment watch is `shared/workspace/**`. Category directories are not
source packages or broad deployment watches. Service configuration fields live
with their service/capability; dependencies contain no imports from this module.
