# Briareus contracts / invocation-events

This leaf owns the `briareus_invocation_events` module.

Consumers: control-panel-api, gateway, github, gitlab, web, server, analysis, ghidra, observability.

Its deployment watch is `shared/contracts/invocation-events/**`. Category directories are not
source packages or broad deployment watches. Service configuration fields live
with their service/capability; dependencies contain no imports from this module.
