# Retired Coolify monolith — historical reference only

The old `mcp-bridge` single Docker Compose application, its internal OAuth issuer, SQLite Management service and combined Web/Observability/Files/Terminal interfaces are **not V1**. The former `legacy-mcp-bridge` GitHub branch has been removed.

**Do not deploy** a recipe from this directory or follow former instructions to reconfigure the retired resource. There is no current `auth` or `management` application to create.

Use the live [V1 deployment guide](../../docs/operations/deployment.md), [configuration](../../docs/operations/configuration.md), [source catalog](../services.json), and [service ownership](../../docs/services/README.md). Old volume/secret data may still require an explicitly approved archival or recovery plan; removing a Git branch is not authorization to destroy such data.
