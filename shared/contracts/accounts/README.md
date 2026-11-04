# Briareus contracts / accounts

This leaf owns the `briareus_account_contracts` module.

Consumers: control-panel-api, gateway, github, gitlab, web, server, analysis, ghidra, observability.

Its deployment watch is `shared/contracts/accounts/**`. Category directories are not
source packages or broad deployment watches. Service configuration fields live
with their service/capability; dependencies contain no imports from this module.
