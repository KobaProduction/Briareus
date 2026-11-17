# Shared Rust V1 service discovery

`briareus-service-discovery-rs` accepts generic provider `ServiceIdentity`
(id, name, group); there are no SigNoz-specific keys or names. It implements
the private Valkey inventory and 20-second renewable instance leases plus a
bounded, read-only RESP `SCAN`/`GET` reader for Gateway. It never holds user
authority, credentials for upstream providers or application data.

Gateway must separately probe each active service's private
`/health/discovery` endpoint and confirm identity and environment. Discovery
failure must not yield authorization or retain stale available endpoints.
The library is an explicit consumer dependency, not a deployed container.
