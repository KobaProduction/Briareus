# Briareus telemetry

This leaf owns the `briareus_telemetry` module.

Consumers: control-panel-api, gateway, github, gitlab, web, server, analysis, ghidra, observability.

Its deployment watch is `shared/telemetry/**`. Category directories are not
source packages or broad deployment watches. Service configuration fields live
with their service/capability; dependencies contain no imports from this module.

`DEPLOYMENT_ENVIRONMENT` is required and identifies the deployment in
`deployment.environment.name`. Use an operator-assigned name of up to 63 characters:
lowercase letters, digits, dots, underscores and hyphens, starting with a letter or digit.
