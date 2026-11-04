# Briareus policies / github

This leaf owns the `briareus_github_policy` module.

Consumers: control-panel-api, github.

Its deployment watch is `shared/policies/github/**`. Category directories are not
source packages or broad deployment watches. Service configuration fields live
with their service/capability; dependencies contain no imports from this module.
