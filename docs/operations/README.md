# V1 operations and delivery

This directory contains **procedures**, separate from architectural ownership:

- [Deployment and Coolify](deployment.md) — topology and rollout boundary.
- [Node identity and OIDC](node-and-identity.md) — roles, issuer and independent nodes.
- [Configuration ownership](configuration.md) — public variables and protected secrets.
- [Build, Compose and Watch Paths](build-and-watch-paths.md) — generated inputs and saved settings.
- [Storage and browser lifecycle](storage-and-browser.md) — persistent data boundaries and Chromium/Playwright separation.
- [Database migrations and recovery](database-and-recovery.md) — explicit backends and rollback.
- [Test and acceptance levels](testing.md) — local, CI, integration and runtime proof.
- [Git, workspace and agent coordination](git-and-worktrees.md) — one canonical repository and temporary linked worktrees.
- [Historical materials](../history/README.md) — explicitly non-operative legacy documents.

The current deployment manifest is `deploy/services.json`; generated owner entrypoints are `services/**/docker-compose.coolify.yaml`. The historic `deploy/coolify` monolith is **not** a V1 deployment recipe.

Any required secrets, volumes, Coolify resources, user grants or rollout steps must be checked in the live environment. Documentation and source checks alone do not authorize a production cutover. For source-specific behavior follow the [core](../core/README.md), [services](../services/README.md), and [Hands](../hands/README.md) owners.
