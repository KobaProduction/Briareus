# Briareus policies / terminal

This leaf owns the `briareus_terminal_policy` module.

Consumers: control-panel-api, server.

Its deployment watch is `shared/policies/terminal/**`. Category directories are not
source packages or broad deployment watches. Service configuration fields live
with their service/capability; dependencies contain no imports from this module.
