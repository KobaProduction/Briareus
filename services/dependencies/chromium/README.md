# External Chromium dependency

This image contains Debian Chromium, Xvfb, nginx and upstream Supervisor only.
Its build context is this directory: it neither copies nor imports Briareus
services/shared packages, and has no application Python manifest or lock.

- CDP and health are private on port 9222; nginx handles Chromium's loopback
  binding and CDP discovery authority without an application proxy.
- Supervisor XML-RPC is private on port 9001 at `/RPC2`. User `browser` uses the
  required runtime `BROWSER_CONTROL_TOKEN`; no credential is included in the image.
- The Web service owns browser authorization, policy, extensions and lifecycle
  requests. It may write `/browser/launch-arguments.json` before an explicit
  start/restart. The generic launcher reads that data once, without watching it.
- Restarting/rebuilding Web or shared code does not stop the running browser.
  A Supervisor stop is explicit; the persistent profile remains on `/browser`.
- Workspace and download mounts are runtime data, never build/source inputs.

The Debian image index is pinned by digest. Updates to this infrastructure
recipe are deliberate dependency deployments, independent of application code.

Completed native downloads use `BROWSER_DOWNLOADS_PATH`, default
`/workspace/browser/downloads`, on the same runtime workspace mount as Server.
Chromium Preferences are updated only at a deliberate browser process start.
Web may also persist its Playwright-managed transfer into that directory.
