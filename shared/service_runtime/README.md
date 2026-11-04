# Briareus service runtime

This leaf owns the `briareus_service_runtime` module.

Consumers: control-panel-api, gateway, github, gitlab, web, server, analysis, ghidra, observability.

Its deployment watch is `shared/service_runtime/**`. Category directories are not
source packages or broad deployment watches. Service configuration fields live
with their service/capability; dependencies contain no imports from this module.
