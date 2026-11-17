# Scenario: One-shot Bootstrap before Backend

Load when an image or service requires database migrations, initial roles/tenants, schema state, first admin, storage preparation or other **pre-start** work. Bootstrap belongs to the deployment **lifecycle**, not to a business ENV toggle; consult `deployment-runtime.md`, `docker-compose.md` and service-specific instructions.

## Owner and ordering

A bootstrap task may live with the backend (`deploy/backend/bootstrap/`) or with its stable dependency stack (`deploy/dependencies/bootstrap/`), depending on who owns the durable change. A one-shot helper in the **same Compose entrypoint** normally needs no second Coolify resource. It should have only the permissions and mounts it needs, then exit. Do not make the persistent application privileged just because the one-time initializer needs elevated rights.

Example **shape** for an application-specific initializer image that is already provided by the service repository:

```yaml
services:
  database:
    image: postgres:18
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?}
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d postgres"]
      interval: 10s
      timeout: 3s
      retries: 10
  bootstrap:
    image: <owned-initializer-image>
    restart: "no"
    depends_on:
      database:
        condition: service_healthy
    # Command and credential access come from the owning project.
  backend:
    image: <owned-backend-image>
    depends_on:
      bootstrap:
        condition: service_completed_successfully
```

This is **illustrative, not a standalone manifest**. Replace placeholders only using approved project sources; supply actual durable PostgreSQL volume, connection configuration, scopes and migration tooling before use. A Compose parser may treat one-shot completion or health-gated startup differently; verify support in the deployed Coolify version. Cross-resource dependencies cannot be expressed with Compose `depends_on` and require separately verified readiness/cutover ordering.

## Operational contract

1. Discover authoritative schema and provisioning mechanism. Never improvise a SQL script or a default administrator password simply because bootstrap is needed. One-off roles/admin/service accounts belong to the **specific application** and its setup procedure, not the universal ENV glossary.
2. Establish **idempotency**: re-running migration/create-if-absent operations is safe or rejected with a clear state diagnostic. Decide whether this job runs on first install, every update, after schema changes or under explicit operator action. A job that exited successfully once is not automatically re-executed on a new deployment.
3. Protect secrets: pass runtime references only, not secrets pasted in image layers, init scripts, logs, `content:` File Mounts or shell history. Provision operators/users by an authorized setup mechanism.
4. Distinguish dependency health (`pg_isready` can mean accepting connections) from readiness for this application's schema. Backend starts **only after successful required bootstrap**; temporary failure must not silently start an incompatible backend.
5. Capture failure/retry state and rollback. Schema changes can be forward-only; an older Git revision or image may **not** roll back data. Back up and test compatibility before touching live state.

## Acceptance

Demonstrate clean empty-state install, a repeat deploy on existing state, a failed bootstrap that blocks backend startup, a safe retry and a real consumer query. Confirm bootstrap exits and leaves no privileged long-running container. For complex vendor-specific initialization, link the owning service runbook rather than copying product-specific instructions here.
