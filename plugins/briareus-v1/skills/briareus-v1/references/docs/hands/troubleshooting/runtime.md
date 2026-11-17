# Discovery, Chromium and observability error classification

**Owners:** [Hands catalogue](../README.md),
[Playwright](../browser.md), [SigNoz](../telemetry.md) and
[Chromium/storage lifecycle](../../operations/storage-and-browser.md).

## Many Hands report `Service registration unavailable`

[Issue #554](https://github.com/KobaProduction/Briareus/issues/554)
records 406 registration WARN events from 10 Hand processes over one
measured 24-hour window, along with transient Valkey timeout, DNS and
subscriber disconnect messages. This establishes **observed warnings**,
not a proven persistent Valkey outage or 406 notification deliveries.
A later healthy Valkey `PONG` and zero restarts do not disprove earlier
transient faults.

Correlate the affected services and registration timestamps with
Valkey reachability, the actual discovery leases and Gateway routing.
An installed Hand or a healthy container is not proof of a current
lease, route or user authorization. Keep service discovery distinct
from authentication. Do not restart all Hands to hide repeating warnings.

**Deployment caution:** #554 recorded a shared discovery change watched
by **17** Coolify applications, with RAM/swap under pressure. Before editing
shared discovery, inspect *current saved* Watch Paths and stage any rollout;
do not infer the blast radius from source files alone.

## Stale element/page is not a Chromium crash

The same [issue #554](https://github.com/KobaProduction/Briareus/issues/554)
documents a confirmed fix to classify known stale element/page caller-state
errors at INFO severity and a repeated close-after-disconnect fix.
If an element reference becomes stale, re-read the current page/tab state
and obtain a fresh ref. Replaying the old ref or restarting Chromium is
not a justified response to a stale element.

A real CDP disconnect, Chromium cgroup OOM or transport timeout is
different. Inspect Playwright and Chromium owners separately. Dependencies
owns Chromium process/profile and memory limits; Playwright owns session
and reconnect logic. A `CHROMIUM_MEMORY_LIMIT` setting change does not
prove the live cgroup changed: verify effective limit and OOM counters
after the relevant rollout. Do not delete a browser profile to cure
a single click failure.

## Pressure versus crash cause

[Issue #367](https://github.com/KobaProduction/Briareus/issues/367)
confirmed a 2 GiB Terminal cgroup OOM and a separate host reboot, but
**not** that the OOM caused the reboot. Check per-process/cgroup memory,
host state and actual restart evidence before claiming root cause or
raising all resource limits. Avoid concurrent heavy builds on a
constrained node without checking resource scope.

## SigNoz logs versus delivered alerts

Issue #554's ERROR/WARN totals are **log events**. The read-only SigNoz
MCP does not prove actual alert deliveries or current alert rules.
Inspect rule definitions, evaluation windows and notification policies
through an authorized management view before making noise-reduction
claims. Preserve true ERROR for crashes and prolonged registration loss.

**Completion:** selected MCP remains reachable through Gateway,
evidence distinguishes caller error from crash, discovery recovers,
and any claimed alert reduction is measured from real deliveries.
