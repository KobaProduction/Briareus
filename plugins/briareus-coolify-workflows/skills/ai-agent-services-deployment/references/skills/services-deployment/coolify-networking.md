# Coolify Networking and Public Routing

Load when a deployment uses shared networks, domains or external access. For related frontend/backend/dependencies prefer a private shared network **per environment**, verifying actual membership. Keep a resource's private networks when they enforce a real trust boundary. The Destination label alone does not prove network attachment.

## Internal vs external networking

### Coolify destinations and Compose network ownership

- **Destination selection is not Compose attachment.** A Destination has a display **Name** and a separate, actual Docker **Network**. Git-backed Docker Compose applications use their resource-specific network by default; enable **Advanced → Docker Compose → Connect To Predefined Network** for each resource that must also join its selected Destination.
- Let Coolify inject the selected Destination's actual network into the generated deployment Compose. Do not hard-code the Destination's display name as an `external: true` Compose network or invent another shared network merely to mirror a UI selection. Explicit Compose network management needs a separate approved ownership reason.
- Verify the actual Docker Network exists on the target host, the enabled setting, generated network declarations, container membership and cross-resource DNS/port reachability. A Destination record alone does not prove that Docker created its network. On missing-network errors, diagnose the Destination/network provisioning path before modifying Compose; check health-gated startup behavior in the deployed parser version.

Internal traffic should stay internal.

Prefer:

```text
api -> postgres:5432
collector -> exporter:9550
frontend -> backend:8080
```

over host/LAN hairpins such as:

```text
api -> 192.168.x.x:5432
collector -> host-ip:9550
```

Rules:

- use Docker service DNS and fixed container ports for internal communication;
- use `expose:` to document/discover internal ports when useful;
- use `ports:` only when a host or external consumer really needs the port;
- do not publish metrics/admin/debug endpoints merely because another container consumes them;
- mutable remote hosts, cross-server targets, bind addresses and externally meaningful ports belong in required runtime variables.

## Public-route inventory before generating domains

Before supplying Coolify Application settings, derive the public/private route inventory from the **accepted product/API contract**, not from whichever containers happen to exist or which endpoints are currently mounted. For each intended route identify its owner Compose service, externally used hostname/protocol, internal listener port, consumer, and activation/security prerequisite. If OAuth and MCP use separate ingress, identify public issuer/discovery/login/token routes separately from the MCP gateway. A health-only stub does **not** satisfy the required OAuth route, and a not-yet-active public service must not be mistakenly classified as permanently internal. Do not expose the private identity/data owner merely because it participates in authentication.

## Public domains: URL by default

For public HTTP(S) routes declare `SERVICE_URL_<SERVICE>_<PORT>: /` on the receiver. `_PORT` gives Coolify its **Internal Port**; the generated value is a URL, not a hostname. If the app needs an issuer hostname, consume `${SERVICE_FQDN_<SERVICE>}` without a suffix. Do not replace the URL route with `SERVICE_FQDN_<SERVICE>_<PORT>: /`. This does not create two public routes. Verify the parser supplies the unsuffixed FQDN; internal-only services need neither.

Match actual service name (normalize separators), internal port and path. Repeat under Coolify `extends` when necessary for parser discovery. Generated routes are service-keyed; use separate minimal ingress adapters for independently editable domains if needed. Never hand-populate magic values.

```yaml
services:
  app:
    environment:
      SERVICE_URL_APP_8080: /
      APP_EXTERNAL_URL: ${SERVICE_URL_APP_8080}
```

`SERVICE_URL_*` includes scheme. `SERVICE_FQDN_<SERVICE>` is portless; `SERVICE_FQDN_<SERVICE>_<PORT>` may include `:port`, so never pass it as an issuer, forwarded Host or Traefik `Host()`. Verify the generic value after domain edits; require a separate origin only if needed.

### Domains, Shared and TLS

Coolify Domains/wildcard controls proxy routing and certificates; DNS/HTTPS require verification. Shared values (e.g. `{{environment.PUBLIC_URL}}`) supply ordinary app ENV, **not** managed Domains or magic directives. Updating Shared does not update proxy routing or certificates.

**Parser gate:** Coolify 4.4.1 sometimes interpolated `${SERVICE_URL_*}` before generation. Verify route, Deployable Compose and **resolved app URL/issuer** (plus OAuth discovery/redirects). On failure approve an explicit-origin fallback; do not force duplicate URL/FQDN or additional Required URLs globally.
