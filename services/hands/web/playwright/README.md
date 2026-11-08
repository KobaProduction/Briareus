# Playwright

One browser provider with internal and external modes at `/mcp`. Internal browser tools
and the Browser Operator attach to the independent Chromium dependency. External mode
proxies the explicitly configured official Playwright MCP under the `external` namespace.
The provider owns Browser Operator `/operator/ws` and private `/cdp/page/{target_id}` routes.
The native CDP transport does not require Google's Chrome DevTools MCP package.

Browser downloads share `SERVER_MOUNT_PATH/browser/downloads` with Server. Browser profile
volumes and external browser policy retain their existing ownership and configuration.
