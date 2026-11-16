# Playwright Hand — browser

**Catalog:** `playwright`. **Source:** [Playwright README](../../services/hands/web/playwright/README.md). **Public MCP:** `/web/playwright/mcp`.

A single Playwright MCP supports the internal Chromium dependency and an explicitly configured external Playwright upstream. External mode is a **mode of the same Hand**, not a new top-level Web MCP. The Browser Operator shares the managed persistent browser with this Hand; it is not a separate DevTools MCP deployment.

Browser downloads are placed in the shared Server workspace; browser profile and transient transfer volumes remain separate. Playwright holds session state and configurable connection/click deadlines; the independent Dependencies resource owns the running Chromium process and its cgroup limits. A Playwright redeploy need not restart Chromium.

## Failure classification

A blocked click is a caller-action warning when another element intercepts pointer events; the Hand does not force-click through overlays. A disconnected/OOM Chromium, CDP handshake timeout, failed context or transport failure is a **real runtime error**; do not conceal it as caller misuse. Background reconnects use bounded backoff. Check Chromium `memory.events` and actual cgroup state before changing timeouts or memory.

See [source settings and behavior](../../services/hands/web/playwright/README.md) and [Chromium dependency](../../services/dependencies/chromium/README.md). There is no Curl MCP or separate Chrome DevTools MCP.
