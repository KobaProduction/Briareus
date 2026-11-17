# Build inputs, Compose and Watch Paths — V1

Each resource in [`deploy/services.json`](../../deploy/services.json) is an independently deployable application. The catalog has four required core entries and eleven optional Hand entries; it contains the authoritative source/Compose/Watch Path selection. Hand images typically consume the shared `deploy/templates/mcp-service.yaml` settings.

## Generating and validating inputs

From the repository root:

```sh
python scripts/briareus_catalog.py --check
python scripts/briareus_dockerfiles.py --check
uv run --frozen --no-env-file --group quality python scripts/briareus_coolify.py --check
```

When changing actual imports or dependencies, regenerate the relevant catalog/Dockerfile/Coolify inputs with their corresponding scripts, review generated changes, then rerun `--check`. Validation of generated files does not update Coolify's saved Application variables or Watch Paths.

Each source owner owns its manifest, frozen `uv.lock`, Dockerfile and Compose entrypoints. Production installs the **service-owned lock**, not an arbitrary resolution from root development dependencies. Dependency images must not copy shared Briareus application source.

## Watch Paths and isolation

Watch the owning service directory and the explicitly consumed **shared leaf packages**; do not Watch all of `shared/**` or the entire repository. MCP Hands also consume the shared deployment-template directory. Independent control-plane/Hand updates should not trigger a Dependencies rebuild or unrelated services.

Use the correct source Build/Base Directory and service-owned generated `docker-compose.coolify.yaml` for Coolify; actual saved values and parser behavior are independently verified. The public Gateway is one receiver; all internal resources attach to the same node's private Destination/network, not a host-level bridge with exposed PostgreSQL/CDP ports.

The operator may export a private Watch Path handout with:

```sh
python scripts/briareus_catalog.py --export .local/briareus-v1-coolify/watch-paths.txt
```

That export is ignored local state and should be deleted after use; it is not a source of truth for automatically saved Coolify settings. Do not create extra project clones or persistent ad-hoc workspaces for handouts.

See [deployment](deployment.md), [core sharing](../core/shared-and-discovery.md) and [Git/worktrees](git-and-worktrees.md).

## Build-time synchronization of external agent skills

Dockerfiles for GitHub, GitLab and Coolify contain a synchronization hook for
https://github.com/ArthurKoba/ai-agent-workflow . Each build resolves upstream
main to one SHA, downloads the immutable archive and installs only allowlisted
documentation into the Hand image. Its SOURCE.json contains the upstream SHA
and SHA-256 checksums. Mandatory missing documents or download failures
reject the build; reference material is not copied into Briareus Git history.

These snapshots are immutable for each image. When the upstream repo changes,
the Hands do not automatically restart, and Coolify does not start a build just
because a different repository changed. Full automation needs a separate
cross-repository push/webhook trigger plus adequate credentials; no trigger or
scheduled checking is active yet. Rebuilds must verify the remote ADD source
was refreshed rather than assuming local BuildKit cache was invalidated.
The running container version and installed skill provenance must be checked
after deployment.

The workflow repository defines generic process guidance; repository-specific
rules, operator approval and real API permissions retain precedence. Clients
can access packaged documents through Skills resources or the
read_workflow_reference tool.
