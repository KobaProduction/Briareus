import { reactive, readonly, watch } from "vue"
import { projectContext } from "./project-context"
import { refreshAuthenticatedProjection } from "./refresh-identity"
import { browserTelemetry } from "./browser-telemetry"
import { platformPort } from "../api/port"
import { normalizeUiError } from "./errors"
import { pageActivity } from "@/shared/lib/page-activity"
import type { ScopedEvent, ScopeSelection } from "./contracts"
import { verifiedDecisionVersion } from "./scope-lifetime"

/** Independent of the old global cookie-topic bus: requires an approved authenticated port. */
const subscribers = new Set<(event: ScopedEvent) => void>()
const state = reactive({
  status: "idle" as "idle" | "connecting" | "connected" | "reconnecting" | "blocked" | "error",
  retryAttempt: 0,
  lastEventAt: "",
})
let stopSocket: (() => void) | null = null
let connectingController: AbortController | null = null
let reconnectTimer = 0
let connectionVersion = 0

function teardown(resetRetry = true): void {
  // A closed source stream cannot retain another principal's diagnostic data.
  browserTelemetry.clear()
  ++connectionVersion
  window.clearTimeout(reconnectTimer)
  reconnectTimer = 0
  connectingController?.abort()
  connectingController = null
  const close = stopSocket
  stopSocket = null
  close?.()
  if (resetRetry) state.retryAttempt = 0
  state.status = "idle"
}

function matches(event: ScopedEvent, scope: ScopeSelection): boolean {
  if (scope.kind === "project") {
    if (event.projectId === scope.projectId) return true
    // A selected Team-owned Project inherits only the resources of ITS Team.
    const ownerTeamId = projectContext.state.projects.find(item => item.key === scope.projectId)?.ownerTeamId
    return event.projectId === null && Boolean(ownerTeamId && event.teamId === ownerTeamId)
  }
  if (scope.kind === "team") return event.projectId === null && event.teamId === scope.teamId
  return scope.kind === "operator" && event.projectId === null && !event.teamId
}

function canConnect(): boolean {
  const scope = projectContext.selection()
  return Boolean(platformPort.value?.bff&&platformPort.value.capabilities?.scopedRealtime===true&&
    projectContext.coreOwnerReady()&&projectContext.state.user?.active&&scope&&
    scope.kind!=="account"&&pageActivity.isActive())
}

function scheduleReconnect(): void {
  if (!canConnect()) return
  window.clearTimeout(reconnectTimer)
  const delay = Math.min(30_000, 1_000 * 2 ** Math.min(state.retryAttempt++, 5))
  state.status = "reconnecting"
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = 0
    void connect(false)
  }, delay)
}

interface StreamLease {
  version: number
  controller: AbortController
  revision: number
  scope: ScopeSelection
}
function streamCurrent(lease: StreamLease): boolean {
  return lease.version === connectionVersion && !lease.controller.signal.aborted &&
    projectContext.state.revision === lease.revision
}
function receiveEvent(event: ScopedEvent, lease: StreamLease): void {
  if (!streamCurrent(lease)) return
  // Principal revocation applies even to a Team-less scope.
  if (event.kind === "principal-revoked") { projectContext.clear(); return }
  const securityChange = event.kind === "access-revoked" || event.kind === "permissions-changed"
  const globallyAddressed = securityChange && event.projectId === null && !event.teamId
  if (!matches(event, lease.scope) && !globallyAddressed) return
  if (securityChange) {
    // An event invalidates grants; only authenticated refresh can restore them.
    projectContext.selectNone()
    void refreshAuthenticatedProjection()
    return
  }
  state.lastEventAt = new Date().toISOString()
  for (const listener of subscribers) listener(event)
}
function connectionFailed(error: unknown): void {
  const issue = normalizeUiError(error)
  if (issue.kind === "unauthorized") { projectContext.clear(); return }
  if (issue.kind === "forbidden") { projectContext.selectNone(); return }
  state.status = "error"
  browserTelemetry.error("app", "realtime")
  scheduleReconnect()
}
async function connect(resetRetry = true): Promise<void> {
  teardown(resetRetry)
  const port = platformPort.value
  const scope = projectContext.selection()
  if(!port?.bff||port.capabilities?.scopedRealtime!==true||!scope||scope.kind==="account"||
     !projectContext.coreOwnerReady()||!projectContext.state.user?.active){
    state.status = "blocked"
    return
  }
  if (!pageActivity.isActive()) {
    state.status = "idle"
    return
  }
  const version = connectionVersion
  const controller = new AbortController()
  connectingController = controller
  const revision = projectContext.state.revision
  const lease: StreamLease = { version, controller, revision, scope }
  state.status = state.retryAttempt ? "reconnecting" : "connecting"
  try {
    const decisionVersion = verifiedDecisionVersion(scope)
    if ((scope.kind === "project" || scope.kind === "team") && !decisionVersion) {
      state.status = "blocked"
      return
    }
    const dispose = await port.realtime.connect({ scope, revision, signal: controller.signal, decisionVersion }, event => {
      receiveEvent(event, lease)
    })
    if (!streamCurrent(lease)) {
      dispose()
      return
    }
    stopSocket = dispose
    state.status = "connected"
    browserTelemetry.lifecycle("ok")
    state.retryAttempt = 0
  } catch (error) {
    if (version !== connectionVersion || controller.signal.aborted) return
    connectionFailed(error)
  } finally {
    if (connectingController === controller) connectingController = null
  }
}

const stopSourceWatch=watch(()=>[
  projectContext.state.revision,projectContext.coreOwnerReady(),platformPort.value,
] as const,()=>{void connect()},{immediate:true})
const stopActivity=pageActivity.subscribe(active=>{
  if (!active) teardown(false)
  else if (canConnect() && !stopSocket && !connectingController) void connect(false)
})

if(import.meta.hot)import.meta.hot.dispose(()=>{
  stopSourceWatch();stopActivity();teardown();subscribers.clear()
})
function subscribe(listener: (event: ScopedEvent) => void): () => void {
  subscribers.add(listener)
  return () => { subscribers.delete(listener) }
}
export const scopedEvents = { state: readonly(state), subscribe, disconnect: teardown, reconnect: () => void connect() }
