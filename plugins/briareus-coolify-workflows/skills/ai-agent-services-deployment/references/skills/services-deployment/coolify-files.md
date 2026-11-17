# Coolify Managed Files and Telemetry

Load when an application needs an editable mounted configuration file or a collector/telemetry deployment. Keep service-specific config semantics in the owning repository, not the universal skill.

## Editable File Mount

Coolify can create and manage one file through Compose `content:`. This is a **File Mount** (bind-mounted configuration), not a Docker named volume. Its Content is visible and editable under the resource's Persistent Storage / File Mount settings when supported:

```yaml
services:
  app:
    volumes:
      - type: bind
        source: ./managed/config.yaml
        target: /etc/app/config.yaml
        content: |
          key: value
```

- `content:` provides a Git bootstrap/recovery template and causes Coolify to materialize the managed file. Operators can edit the active content in Coolify without editing Compose; the application may need reload/restart to read it. Existing File Storage content may take precedence on redeploy, so **do not assume a new Git template overwrites operator edits**. Keep an intentional source-of-truth/recovery policy.
- If editing in Coolify is required, do **not** declare the Compose mount `read_only: true`. The [Coolify File Mount guide](https://coolify.io/docs/core/persistent-storage/storage-mounts/file-mounts) states that a Compose read-only file is not dashboard-editable. This is a conditional caveat, not a reason to prohibit read-only mounts for configurations intentionally managed elsewhere.
- Keep passwords/tokens out of readable managed content. The application may read approved runtime ENV (e.g. Alloy `sys.env("NAME")`); `content:` itself is **not** a universal secret interpolator. Store actual secrets with the approved secret owner.
- If `extends` hides file metadata from the Coolify parser, redeclare the `content:` mount under the owning service in `docker-compose.coolify.yaml`. If content is duplicated, keep both copies synchronized.

## Parser and storage boundaries

- On Coolify 4.3.23, a repository-relative file bind without `content:` can be classified as a directory; verify the deployed parser before relying on a Git file bind. Where a tracked file is authoritative, prefer preserving repository files rather than creating a separate editable copy.
- Keep named volumes/directories for durable data and overlay only the managed configuration file. Do not overwrite unknown live File Storage during migrations. Removed managed records or changed mounts may require a new parse; test the actual deployed Coolify release.
- File Mounts are not covered by scheduled Coolify volume backups. Preserve edited content using the owning project's recovery process; do not treat the live editor as source control.

Avoid unnecessary host `/etc/localtime`/`/etc/timezone` mounts when the image already supports `TZ`.

## Metrics / observability

- Shared backend credentials and endpoints belong to the relevant Shared/secret scope; service-local labels can remain in Compose when invariant.
- Use internal Docker DNS for exporters/collectors; publish metrics ports only when an external consumer needs them.
- A local OpenTelemetry collector is optional; use it for justified routing/protocol requirements, not by default. Preserve existing scraping, relabeling and buffering semantics when migrating its configuration.
