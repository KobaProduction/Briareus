# Briareus python / secret-files

This leaf owns the `briareus_secret_files` module.

Consumers: control-panel-api, gateway.

Its deployment watch is `shared/python/secret-files/**`. Category directories are not
source packages or broad deployment watches. Service configuration fields live
with their service/capability; dependencies contain no imports from this module.
