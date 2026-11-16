# Dependencies — V1 node infrastructure

**Owner:** `services/dependencies`.

One independently deployed resource contains three third-party containers: **PostgreSQL, Valkey and persistent Chromium**. It has no Briareus application source. Dependency changes are watched only within its own owner directory; a Hand/UI/API update must not force this resource to rebuild.

PostgreSQL is the production Control Panel database. Valkey supplies cache and discovery leases, not a second source of truth. Chromium exposes its private browser control to the Playwright Hand and keeps a separate persistent profile and transfer storage. Chromium memory/swap limits are configurable through deployment variables; changing a Coolify variable and changing a live container's cgroup are distinct operations.

The external identity provider and native Ghidra MCP are **not** started by Dependencies. See [source README](../../services/dependencies/README.md), [Chromium](../../services/dependencies/chromium/README.md), [browser Hand](../hands/browser.md), and [deployment](../operations/deployment.md).
