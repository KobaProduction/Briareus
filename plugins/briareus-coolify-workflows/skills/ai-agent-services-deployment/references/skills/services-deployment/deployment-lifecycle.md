# Deployment Lifecycle and Infrastructure Migration

Load for new/upgrade/migration/recovery planning, bootstrap with durable effects, and production rollback. Approval of the architecture and privileges precedes changing existing deployments. Keep distinct evidence for source, parser, runtime, consumer and cutover acceptance.

## Acceptance contract and lifecycle matrix

Before implementation, record the small set of deployment invariants that must survive every fix, for example:

- one vs multiple deployment entrypoints;
- allowed persistent services;
- which component may ever hold host/root privileges;
- state/backup ownership;
- zero-touch vs allowed post-install/manual steps;
- clean-host assumptions;
- rollback dependency that must stay alive until replacement acceptance.

Then model materially different lifecycle rows:

| State | Expected behavior |
| --- | --- |
| clean install | all required prerequisites are created or a precise unsupported-state error is raised |
| repeat deploy | healthy state is checked/idempotently preserved; no destructive reinstall |
| partial/stale prior state | known legacy state has an explicit migration; unknown state fails closed |
| restart/reboot | persistent runtime reconnects without re-enrollment/manual repair where required |
| version upgrade | pinned/versioned components converge according to an explicit upgrade contract |
| rollback | known-good dependency remains usable until replacement acceptance |

Do not let the most recent failed deploy rewrite this table implicitly.

## Browser/admin UI secret exposure

Treat an authenticated infrastructure browser session as a privileged secret-capable surface.

Masking in an admin UI is not a security boundary once a value is deliberately revealed. In the validated Coolify browser flow:

- a masked secret field was returned to the automation layer only as a redacted value;
- after a human manually activated the visibility/reveal control, the plaintext became available in the page DOM and therefore to the browser agent.

Operational rule:

- do not reveal real secrets in a shared browser session while an automation/agent has page access unless that disclosure is intentionally authorized;
- prefer inspecting secret names, scopes and references rather than values;
- use non-sensitive canary secrets when testing browser/DOM exposure behavior;
- navigate away or close the privileged page after the operation.

Assume other browser automation systems may have fewer protective filters than the current toolchain.

## Migration from UI-owned configuration

When moving an existing service from an orchestrator UI into Git:

1. capture the current known-good configuration exactly;
2. preserve volume names, persistent data contracts, domains and secret references;
3. commit the recovered configuration as a reference before refactoring it;
4. create the Git-backed deployment resource without destroying the old one;
5. validate the new deployment;
6. cut over only after runtime acceptance;
7. retire the old UI-owned definition after rollback is no longer required.

Do not combine recovery, refactoring and production cutover into one unverified change.

## CI runner infrastructure

When the goal is centralized compute rather than replacement of a provider's CI language, prefer native CI with self-hosted runner management:

    GitHub Actions ----\
                        +--> managed self-hosted compute/cache
    GitLab CI ---------/

Preserve provider-native workflow files, logs, checks and artifacts when possible.

A runner manager may own:
- host/worker pools;
- scheduling and queues;
- ephemeral runner lifecycle;
- cache;
- CPU/RAM/PID limits;
- isolation;
- telemetry.

It should not force migration to another pipeline language unless that is an explicit product decision.

## Validation levels

Keep these states separate:

- repository/config source validated;
- manifest parsed;
- deployment succeeded;
- service healthy;
- real consumer path accepted;
- replacement/cutover accepted.

A successful Compose parse or deployment is not proof that the service is ready for production use.

## Rollback

For infrastructure replacement:
- preserve the known-good deployment until the replacement is accepted;
- record enough configuration to reconstruct it;
- keep persistent data ownership explicit;
- avoid destructive deletion during exploratory migration.

Useful retired configurations may remain as clearly marked reference stacks when they preserve operational knowledge.
