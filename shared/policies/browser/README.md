# Briareus policies / browser

This leaf owns the `briareus_browser_policy` module.

Consumers: control-panel-api, web.

Its deployment watch is `shared/policies/browser/**`. Category directories are not
source packages or broad deployment watches. Service configuration fields live
with their service/capability; dependencies contain no imports from this module.
