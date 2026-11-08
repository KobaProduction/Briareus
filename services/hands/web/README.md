# Web providers

Playwright is the browser provider. Its independent service lives in `playwright/`.
The internal mode attaches to the persistent Chromium dependency; the external mode
connects to the configured official Playwright MCP and uses the `external` tool namespace.
Both modes belong to one Playwright MCP. There is no Chrome DevTools MCP process,
no aggregate Web MCP, and no curl/HTTP MCP tool family. Curl remains available in Server.
