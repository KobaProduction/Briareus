# Briareus hand runtime

This leaf owns the `briareus_hand_runtime` module.

Consumers: github, gitlab, web, server, analysis, ghidra, observability.

Its deployment watch is `shared/hand_runtime/**`. Category directories are not
source packages or broad deployment watches. Service configuration fields live
with their service/capability; dependencies contain no imports from this module.
