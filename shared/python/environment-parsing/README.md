# Briareus python / environment-parsing

This leaf owns the `briareus_environment_parsing` module.

Consumers: gateway, github, gitlab, web, server, analysis, ghidra, observability.

Its deployment watch is `shared/python/environment-parsing/**`. Category directories are not
source packages or broad deployment watches. Service configuration fields live
with their service/capability; dependencies contain no imports from this module.
