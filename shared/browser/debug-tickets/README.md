# Briareus browser / debug-tickets

This leaf owns the `briareus_browser_debug_tickets` module.

Consumers: control-panel-api, web.

Its deployment watch is `shared/browser/debug-tickets/**`. Category directories are not
source packages or broad deployment watches. Service configuration fields live
with their service/capability; dependencies contain no imports from this module.
