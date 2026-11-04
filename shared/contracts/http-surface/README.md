# Briareus contracts / http-surface

This leaf owns the `briareus_http_surface` module.

Consumers: gateway, github, gitlab, web, server, analysis, ghidra, observability.

Its deployment watch is `shared/contracts/http-surface/**`. Category directories are not
source packages or broad deployment watches. Service configuration fields live
with their service/capability; dependencies contain no imports from this module.
