# Briareus contracts / tool-annotations

This leaf owns the `briareus_tool_annotations` module.

Consumers: gateway, github, gitlab, web, server, observability.

Its deployment watch is `shared/contracts/tool-annotations/**`. Category directories are not
source packages or broad deployment watches. Service configuration fields live
with their service/capability; dependencies contain no imports from this module.
