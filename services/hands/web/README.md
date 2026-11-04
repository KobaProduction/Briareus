# Briareus V1 Web

Browser MCP capabilities, operator UI and DevTools attach to an independent,
persistent Chromium infrastructure container. Web owns browser profile settings,
extension configuration, launch-policy translation and the private Supervisor
adapter. Chromium contains no Briareus/shared code and survives Web client recreation.

Downloads are shared with Server under `SERVER_MOUNT_PATH/browser/downloads`
(default `/workspace/browser/downloads`). File operations and shell processing
belong to Server; structured curl tools have been removed from Web.

Runtime argv/profile files are data, not an image build dependency. A Web source
update does not restart Chromium. Explicit browser lifecycle/extension actions
can request a process restart while preserving its profile.
