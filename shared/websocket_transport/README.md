# Briareus websocket transport

This leaf owns the `briareus_websocket_transport` module.

Consumers: control-panel-api, gateway, web.

Its deployment watch is `shared/websocket_transport/**`. Category directories are not
source packages or broad deployment watches. Service configuration fields live
with their service/capability; dependencies contain no imports from this module.
