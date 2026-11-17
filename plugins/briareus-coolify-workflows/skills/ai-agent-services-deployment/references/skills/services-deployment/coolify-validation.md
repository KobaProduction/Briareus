# Coolify Acceptance and Source Verification

Load when checking a freshly parsed or deployed Compose resource. Generic `docker compose config` and a healthy container are separate from Coolify parser validation and consumer acceptance. Keep test-only resources distinct from production; never redeploy a running service just to resolve uncertainty about parser semantics.

## Deploy and restart acceptance

A Git change does not configure an existing Coolify resource until the **reviewed commit is on the resource's real configured branch** and the orchestrator has parsed/deployed that exact revision. Before telling an operator to deploy, verify the published ref, native Base Directory/Compose location, saved Watch Paths, and whether merge/webhooks will auto-deploy a resource whose database or security prerequisites are still unapproved. A source-level `activation: blocked` label is not an orchestrator stop mechanism. Avoid telling the operator to recreate a resource or to set manually generated magic variables as a workaround.

Choose `restart:` from the accepted failure lifecycle: when an unrepairable configuration/credential/schema/trust failure must stop a service, a policy such as `unless-stopped` causes an endless startup loop, while `restart: "no"` allows inspection after one failure. Do not impose fail-stop on healthy long-lived workers without that contract. Verify the **effective** policy/container after Coolify reparse, rather than assuming that updating Git changed a running container. Diagnose failures from safe, actionable error categories and bounded runtime evidence; an intentionally redacted generic startup exception is not proof of a particular SQL/password cause.

A successful image build, a Coolify deployment marked `finished`, a container marked `running:healthy`, application `/health/live`, readiness/authorization and an external user-facing HTTPS/OAuth/MCP operation are **different acceptance levels**. Check the intended consumer's actual route, DNS/TLS and expected response; missing top-level `fqdn` on a Compose Application alone is not evidence that the service-specific managed domain is absent.

## Fresh-parse validation

Parser-driven features require parser validation, not only YAML validation.

Before declaring the source ready, inspect a fresh Coolify resource and verify:

- every required variable exists, is marked Required and is empty until intentionally set;
- optional variables contain only approved defaults;
- each shared-variable reference points to an existing key at the exact intended scope;
- shared secret references are present without exposing secret values;
- runtime logs/behavior show that shared references resolved to usable values rather than remaining literal `{{scope.KEY}}` strings;
- generated public routes exist in the expected count, under the receiving services and target ports; prefer one `SERVICE_URL_*` per route, permitting `SERVICE_FQDN_*` only for a verified hostname consumer (no mandatory URL+FQDN pair for TLS);
- if the application consumes its own public URL, startup/runtime evidence shows the resolved canonical URL rather than only proving proxy reachability;
- managed file mounts appear at the intended paths;
- internal-only ports are not host-published;
- persistent volumes refer to the intended existing data;
- Compose parser output contains no stale placeholders or unintended generated values.

Then distinguish runtime health from consumer acceptance. Detailed metric queries and product-specific functional tests belong to the owning service runbook, not this deployment skill.

## Source references

Use current documentation for user-facing contracts, then inspect the parser source for version-specific behavior:

- Docker Compose: https://coolify.io/docs/applications/builds/docker-compose
- Service environment variables: https://coolify.io/docs/services/configuration/environment-variables
- Shared variables: https://coolify.io/docs/core/team/shared-variables
- File mounts: https://coolify.io/docs/core/persistent-storage/storage-mounts/file-mounts
- Coolify v4 Compose parser: https://github.com/coollabsio/coolify/blob/v4.x/bootstrap/helpers/parsers.php
- Environment variable model: https://github.com/coollabsio/coolify/blob/v4.x/app/Models/EnvironmentVariable.php

When the deployed version is known, prefer that exact tag/commit over `v4.x` for debugging parser behavior.
