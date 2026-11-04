# Briareus telemetry

This leaf owns the `briareus_telemetry` module.

Consumers: control-panel-api, gateway, github, gitlab, web, server, analysis, ghidra, observability.

Its deployment watch is `shared/telemetry/**`. Category directories are not
source packages or broad deployment watches. Service configuration fields live
with their service/capability; dependencies contain no imports from this module.
