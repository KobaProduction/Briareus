# Briareus policies / gitlab

This leaf owns the `briareus_gitlab_policy` module.

Consumers: control-panel-api, gitlab.

Its deployment watch is `shared/policies/gitlab/**`. Category directories are not
source packages or broad deployment watches. Service configuration fields live
with their service/capability; dependencies contain no imports from this module.
