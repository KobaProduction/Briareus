# Playwright

One browser provider with internal and external modes at `/mcp`. Internal browser tools
and the Browser Operator attach to the independent Chromium dependency. External mode
proxies the explicitly configured official Playwright MCP under the `external` namespace.
The provider owns Browser Operator `/operator/ws` and private `/cdp/page/{target_id}` routes.
The native CDP transport does not require Google's Chrome DevTools MCP package.

Browser downloads share `SERVER_MOUNT_PATH/browser/downloads` with Server. Browser profile
volumes and external browser policy retain their existing ownership and configuration.

When the independent Chromium process exceeds its container memory cgroup limit,
Linux may terminate Chromium renderers while Supervisor and the overall container
remain running. This can surface as a CDP handshake timeout, an HTTP 502 from
the private CDP nginx proxy, or a closed browser context; these are real runtime
failures and must remain observable as errors. Check the Chromium container's
`memory.events` (`oom_kill`), relevant kernel logs and the configured memory
limit before assuming a provider bug or increasing timeouts.

The passive idle-tab cleanup task attempts to reconnect after an MCP restart,
but backs off after a failed CDP attach to avoid repeatedly competing with
foreground browser operations while Chromium is unhealthy. The caller still
receives every actual failed operation, and background warnings are not hidden.
The following optional environment settings are validated and apply only to
Playwright runtime behavior:

- `BROWSER_CDP_CONNECT_TIMEOUT_MS` (default `20000`): attach deadline.
- `BROWSER_IDLE_RECONNECT_BACKOFF_SECONDS` (default `60`): pause between failed
  **background** reconnection attempts. Foreground calls are not rate-limited.
- `BROWSER_IDLE_CLEANUP_INTERVAL_SECONDS` (default `10`): background cleanup
  cadence during normal operation. A successful attach clears the retry delay.

None of these settings changes the Chromium cgroup limit, browser profile,
Supervisor lifecycle, tab closure policy or live host configuration.
