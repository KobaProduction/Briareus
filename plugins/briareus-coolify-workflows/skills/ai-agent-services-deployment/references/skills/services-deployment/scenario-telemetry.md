# Scenario: Telemetry Collector and Editable Coolify Configuration

Load when deploying an infrastructure exporter/Alloy collector, an optional OpenTelemetry Collector, or an application exporting OTLP. This is not a vendor-specific monitoring alert/runbook. Consult `coolify-files.md`, `telemetry-variables.md`, `coolify-compose.md`, and `coolify-networking.md` as needed.

## Separate the two telemetry paths

| Source | Typical path | Input naming owner |
| --- | --- | --- |
| Host/infrastructure metrics | host exporter → Alloy → Prometheus Remote Write/VictoriaMetrics | Remote Write backend's own credential names, **not** `OTEL_ENDPOINT` |
| App logs/traces/metrics | backend/frontend SDK → OTLP endpoint / optional OTel Collector → application observability backend | `OTEL_ENDPOINT`, `OTEL_NAMESPACE`, `DEPLOYMENT_ENVIRONMENT`, `OTEL_SERVICE_NAME` and conditional `OTEL_BEARER_TOKEN` |

A collector is **optional**. Add it when routing, buffering, protocol conversion or security boundary warrants a component, not as a compulsory per-app container. Infrastructure collector instances may be **one per host**, while a shared app-signal collector may serve multiple applications within one environment. Resource separation follows lifecycle and ownership; do not create a separate Coolify resource for every exporter.

## Generic base and Coolify-managed File Mount

Keep the base portable by mounting a **real tracked config file** (example only):

```yaml
# docker-compose.yaml — schematic service excerpt
services:
  collector:
    image: <pinned-collector-image>
    volumes:
      - ./config/collector.yaml:/etc/collector/config.yaml:ro
    environment:
      OTEL_EXPORTER_OTLP_ENDPOINT: ${OTEL_ENDPOINT:?}
```

When operators need **editable file content** through Coolify, the entrypoint can extend the base and declare a managed file explicitly:

```yaml
# docker-compose.coolify.yaml — schematic parser excerpt
services:
  collector:
    extends:
      file: ./docker-compose.yaml
      service: collector
    volumes:
      - type: bind
        source: ./managed/collector.yaml
        target: /etc/collector/config.yaml
        content: |
          # Non-secret initial configuration; real schema is image-specific.
          receivers: {}
    environment:
      OTEL_EXPORTER_OTLP_ENDPOINT: ${OTEL_ENDPOINT:?}
```

These fragments show **mount ownership**, not a deployable collector. If the real collector needs different ENV or config schema, use its official contract. The base tracked bind requires an existing file; preserve the source repository where Coolify must read it. The Coolify `content:` block is **nonstandard Compose** and belongs in the Coolify entrypoint, not the standalone base.

## Editability, secrets and drift

- On supported Coolify versions, File Mount Content is editable under Persistent Storage. A Compose mount declared `read_only: true` is **not editable in the dashboard**; omit it when operator editing is required, or intentionally use read-only when Git owns the content. Changing the mount's writeability is not a substitute for verifying app config reload behavior.
- An existing Coolify File Storage entry can override the bootstrap `content:` on a later reparse. Define which file is authoritative, how operator edits are reviewed/exported, and how it will be restored. Managed files are not covered by ordinary scheduled volume backups.
- Do not inline tokens in `content:`. Write references resolved **by the application** (e.g. Alloy `sys.env("NAME")`) or use a verified secret-file mechanism. The `content:` parser itself is not a generic secrets expander. Keep bearer tokens in protected scope and assemble Authorization headers only at an approved SDK/collector boundary.

## Acceptance boundary

Check that Coolify parses one intended service, Required/default variables and the intended managed mount; confirm a running collector with light healthcheck. Real telemetry success still needs a separate, bounded check at the receiving backend (recent samples/signals, failures/backlog), owned by that specific service runbook. Do not turn every functional metric into a mandatory deployment healthcheck or assume `running:unknown` proves successful export.
