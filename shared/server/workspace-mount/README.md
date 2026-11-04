# Briareus server / workspace-mount

This leaf owns the `briareus_server_mount` module.

Consumers: control-panel-api, github, gitlab, web, server, analysis.

Its deployment watch is `shared/server/workspace-mount/**`. Category directories are not
source packages or broad deployment watches. Service configuration fields live
with their service/capability; dependencies contain no imports from this module.
