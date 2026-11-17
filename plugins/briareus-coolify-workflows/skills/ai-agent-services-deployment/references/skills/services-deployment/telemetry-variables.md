# OpenTelemetry Variable Contract

Load when defining or refactoring telemetry-specific deployment inputs; for cross-resource naming use `variable-glossary.md`. These are **operator names**, not new upstream SDK variables.

## OpenTelemetry — operator contract

| Key | Preferred owner/scope | Required/default | Mapping / meaning |
| --- | --- | --- | --- |
| `OTEL_ENDPOINT` | Team Shared when collector is common | Required when exporting remotely | Translate to `OTEL_EXPORTER_OTLP_ENDPOINT` or collector endpoint |
| `OTEL_BEARER_TOKEN` | Secret Manager, narrowest authorized shared scope | Required **only** if endpoint uses Bearer | Credential, not prebuilt header string |
| `OTEL_NAMESPACE` | Project Shared | Set when multi-service identity is needed | `service.namespace` resource attribute |
| `DEPLOYMENT_ENVIRONMENT` | Environment Shared | Explicit `development` / `production` / `staging` / `test` | `deployment.environment.name` resource attribute |
| `OTEL_SERVICE_NAME` | Resource/Compose, often a fixed literal | Per instrumented service | Official `OTEL_SERVICE_NAME` / `service.name` |

Do not expose module/scope subdivisions as deployment keys merely because code has them; instrumentation scope belongs to the application/SDK unless a real operator input is needed. `OTEL_ENDPOINT`, `OTEL_NAMESPACE`, `OTEL_BEARER_TOKEN` and `DEPLOYMENT_ENVIRONMENT` are **our keys**, not automatically recognized by OTel SDKs. Map them to the consuming SDK/collector once, using `OTEL_RESOURCE_ATTRIBUTES` or native configuration as needed.

Bearer-first **internal policy**: applications/collectors form `Authorization: Bearer <token>` at the supported boundary, without displaying secret headers in Git/Resource ENV. If an SDK needs `OTEL_EXPORTER_OTLP_HEADERS`, generate the proper compatible format internally instead of making a header blob an operator key. That upstream option is **still supported by the OTel specification**; "legacy" describes our discouraged operator workflow, not its standards status. Prometheus Remote Write (e.g. Alloy → VictoriaMetrics) has its own backend credentials and is **not OTLP**.

Upstream authority: [OTLP exporter](https://opentelemetry.io/docs/specs/otel/protocol/exporter/); [deployment semantics](https://opentelemetry.io/docs/specs/semconv/registry/attributes/deployment/).
