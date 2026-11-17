# Coolify Parser State and Migrations

Load before migrating UI-owned resources into Git, changing parser-managed state, volumes, domains or existing Shared references. Preserve known-good deployments and recoverability; diagnose with disposable resources only, never by recreating live services for curiosity.

## Git-backed migration

When converting a UI-owned Coolify service into Git-backed Compose:

1. capture the known-good Compose and parser-managed state;
2. inventory required/shared/default variables;
3. capture generated domains and their target ports;
4. capture managed-file contents;
5. capture old persistent volume names and determine how the deployed Coolify version names replacement volumes;
6. refactor only after the preservation contract is explicit;
7. create/recreate the Git-backed resource and inspect parser output before deployment;
8. when the parser namespaces named volumes to the new resource UUID, do not assume top-level Compose `external:`/`name:` will preserve cross-resource attachment; explicitly copy old volume contents into the new resource volumes after verifying source and destination identities;
9. stop the old service before copying or attaching writable state;
10. deploy and validate;
11. retain the old resource and old volumes as rollback until acceptance.

Do not run two stacks concurrently against the same writable state volume unless the application explicitly supports it.

## Parser state and stale variables

Treat an existing Coolify resource as stateful parser output, not as a pure reflection of the current Git file.

Observed consequences on Coolify 4.3.23:

- variables removed from Compose can remain as stale resource variables until explicitly deleted;
- generated file/domain/storage records can survive source changes;
- a successful reparse does not prove stale state was removed;
- a disposable **diagnostic** resource can distinguish fresh-parser behavior from stale state, but never recreate a real existing application merely to diagnose a domain/ENV mismatch; inspect and preserve its domains, variables, live credentials, volumes and rollout history first.

During migration or refactors, compare current Git requirements with the actual resource variable/storage/domain inventory and remove only entries proven obsolete. Do not delete unknown state merely because it is absent from the latest Compose.

When a parser-managed feature is introduced after a resource already exists, a reparse can materialize the variable/storage record without reproducing the same initialization path as a brand-new resource. If generated state looks impossible or internally inconsistent, recreate a disposable resource from the same Git revision before changing the manifest again. Fresh-resource reproduction distinguishes parser-state drift from source defects.

### Persistent-state migration discipline

Do not repair a named volume by recursively changing ownership or deleting unknown contents merely because a new container UID/GID differs.

For a layout migration:

1. identify which subpaths are durable authority and which are documented recreatable cache/runtime data;
2. whitelist only proven disposable legacy paths for automatic cleanup/migration;
3. validate their expected structure before deleting them;
4. fail closed on unknown siblings/content;
5. re-run the same migration on a regression fixture so repeat deploy remains idempotent.

In user-namespace/rootless scenarios, files created by runner/container identities may appear on the host with subordinate mapped IDs. That alone is not corruption.
