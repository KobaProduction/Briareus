# Git-backed Deployment and Update Scope

Load when Git owns a service definition and an orchestrator owns its live state. Folder/README/watch-path structure belongs to `deployment-layout.md`, not to the parser contract. Use `deployment-lifecycle.md` for upgrade/rollback/migration; use `coolify-compose.md` when Coolify parses a manifest.

## Authority split

Keep three authorities distinct:

1. **Git repository** — desired infrastructure definitions, deployment templates, non-secret configuration, change history and review.
2. **Runtime control plane** — live deployment state, domains, certificates, environment/secrets, persistent resources and service lifecycle.
3. **Observability/acceptance surface** — runtime evidence proving that the deployed service works for its real consumer.

Do not treat any one of these as a substitute for the others.

## Trust boundaries follow authority

A second Compose file, orchestrator resource or repository directory is not automatically a security boundary.

Before splitting privileged provisioning from an application, draw the authority graph:

- who can modify the Git definition;
- who can merge/approve it;
- which orchestrator identity deploys it;
- which credentials/permissions each resource receives;
- whether untrusted jobs/workloads can invoke or mutate the privileged path.

If the same repository/reviewer/orchestrator authority can deploy both resources with the same host privileges, separating them may improve lifecycle clarity but does not materially reduce that authority. Do not trade away a required one-entrypoint/zero-touch contract and call the extra resource isolation unless permissions or deployment authority actually differ.

The useful boundary is often:

```text
trusted infrastructure deployment authority
              |
              +-- temporary host provisioning authority
              |
              `-- persistent unprivileged service
                         |
                         `-- untrusted workload/job
```

Protect the lower-trust workload from the infrastructure control plane. Do not pretend the control plane is untrusted while still granting it the power to deploy arbitrary privileged definitions.

## Public methodology vs private state

Reusable instructions belong in a public/general workflow repository when they do not expose environment-specific state.

Private infrastructure repositories should hold the actual current deployment state, for example:
- concrete Compose manifests;
- service/domain names;
- repository mappings;
- server aliases and resource identifiers;
- watch paths;
- migration state;
- environment-specific runbooks.

Do not put private topology, credentials, host addresses, tokens or current resource IDs into a universal workflow library.

## Git-backed deployment pattern

Prefer a Git-backed application/deployment source when the orchestrator supports it.

Typical flow:

1. infrastructure code changes on a working branch;
2. review/merge establishes the desired state;
3. the deployment platform watches the relevant path or receives a deploy webhook;
4. it reparses the stack and redeploys only that service;
5. runtime and consumer-facing acceptance are verified.

Avoid UI-only Compose definitions when the same configuration can live in Git and be reviewed, recovered and modified by automation.

## Watch-path policy

In multi-service infrastructure repositories, watch **the agreed scope of each resource**, not unrelated resources. One resource may own multiple containers, especially stable dependencies. Determine policy from repository conventions and the user's explicit requirement.

- **Whole service directory:** `deploy/example/**` is valid even when README/runbooks/audits share that folder. Documentation-only edits intentionally redeploy the one service; do not flag this as error or create `compose/` to suppress it.
- **Runtime inputs only:** watch manifest and consumed config/bootstrap paths when that is the expressly chosen policy.
- Do not impose either universally. Preserve established layout, document the agreed glob, verify **persisted** orchestrator state; missing/unrelated-service paths are problems.

## Secrets

Git stores variable names and references, never secret values.

Prefer explicit required-variable contracts:

    environment:
      EXAMPLE_TOKEN: ${EXAMPLE_TOKEN:?}

The actual value belongs in the runtime secret/configuration provider.

Never commit:
- `.env` with real values;
- API tokens;
- private keys;
- webhook secrets;
- runner registration secrets;
- generated credentials.
