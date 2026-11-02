import { computed, onBeforeUnmount, reactive, shallowReactive, watch, watchEffect } from "vue"
import { projectContext } from "./project-context"
import { browserTelemetry, type DiagnosticOutcome } from "./browser-telemetry"
import { platformPort } from "../api/port"
import { normalizeUiError, type UiError } from "./errors"
import { scopedEvents } from "./project-events"
import { refreshAuthenticatedProjection } from "./refresh-identity"
import { verifyOriginalEffect, type EffectOutcome } from "./effect-reconciliation"
import { sourceMutationReady, mutationBlockedIssue } from "./mutation-readiness"
import { sameScope, verifiedDecisionVersion } from "./scope-lifetime"
import { openReconciliation } from "./reconciliation-lifetime"
import { appendVerifiedKeyset } from "./scoped-keyset"
import { commandCoordinator, resourceForAction, type CommandResource, type PendingCommand } from "./command-coordinator"
import { groupVerifiedBffCapabilities, verifiedBffEvidence } from "./bff-evidence"
import type { CommandContext, PlatformPort, QueryContext, ScopeSelection, UiCapability, SourceCommandBinding } from "./contracts"

export interface DomainLoad<T> {
  items:T[]; revision?:string|null; serverLimit?:number; possiblyTruncated?:boolean; observedAt?:string
  nextAfterId?:string|null; hasMore?:boolean; pageSize?:number
}
export type ReadDomain<T> = (port: PlatformPort, context: QueryContext, after?:string|null) => Promise<DomainLoad<T>>
export type WriteDomain = (port: PlatformPort, context: CommandContext) => Promise<unknown>
export { sourceMutationReady } from "./mutation-readiness"
export type LoadStatus = "blocked" | "idle" | "loading" | "ready" | "empty" | "error"

/** Only trusted fixed error KIND enters telemetry. Never raw server code/URL. */
function diagnosticOutcome(error:UiError):DiagnosticOutcome {
  if(error.kind==="uncertain"||error.kind==="unknown"||error.kind==="conflict")return "uncertain"
  if(error.kind==="forbidden"||error.kind==="unauthorized")return "blocked"
  if(error.kind==="invalid")return "rejected"
  return "unavailable"
}
function handlePermissionError(error: UiError): boolean {
  if (error.kind === "unauthorized") { projectContext.clear(); return true }
  if (error.kind === "forbidden") {
    // Never retain stale Team/Project/operator actions after 403 or a
    // decision-version drift. A fresh AUTHENTICATED projection is necessary.
    projectContext.selectNone()
    void refreshAuthenticatedProjection()
    return true
  }
  return false
}

/** Reads and mutations have INDEPENDENT generations: a WS read must not erase an acknowledged write. */
export function useDomain<T>(
  resource: string,
  ability: UiCapability,
  read: ReadDomain<T>,
  scopes: ScopeSelection["kind"][] = ["account", "team", "project", "operator"],
  available: (port: PlatformPort) => boolean = () => true,
  keyOf?: (item:T)=>string,
) {
  const state = shallowReactive({
    items: [] as T[],
    status: "blocked" as LoadStatus,
    revision: null as string | null,
    serverLimit: null as number | null,
    possiblyTruncated: false,
    observedAt: null as string | null,
    nextAfterId: null as string | null,
    hasMore: false,
    pageSize: null as number | null,
    loadingMore: false,
    loadMoreError: null as UiError | null,
    error: null as UiError | null,
    busy: false,
    actionError: null as UiError | null,
    reconciliationRequired: false,
    reconciliationNotice: false,
  })
  let readRun = 0
  let writeRun = 0
  let controller: AbortController | null = null
  let pagination: AbortController | null = null
  let mutation: AbortController | null = null
  let activeWrite: PendingCommand | null = null
  let disposed = false

  function usable(): boolean {
    const scope = projectContext.selection()
    const port = platformPort.value
    // Every protected UI read is served only by a real same-origin BFF
    // composition. The retired global A10 source port is not eligible even
    // if its opaque User/project read projection happens to parse.
    const domains=port?groupVerifiedBffCapabilities(port):null
    const ownerProof=projectContext.state.ownerEvidence
    return Boolean(port&&domains&&available(port)&&scope&&scopes.includes(scope.kind)&&
      projectContext.state.user?.active&&ownerProof&&
      verifiedBffEvidence(ownerProof,projectContext.state.user.key,scope)&&
      projectContext.can(ability))
  }
  function invalidate(): void {
    ++readRun
    ++writeRun
    controller?.abort()
    pagination?.abort()
    pagination=null
    // A discarded in-flight response is an UNKNOWN server write outcome.
    if (activeWrite) commandCoordinator.uncertain(activeWrite)
    activeWrite = null
    mutation?.abort()
    controller = null
    mutation = null
    state.items = []
    state.revision = null
    state.serverLimit = null
    state.possiblyTruncated = false
    state.observedAt = null
    state.nextAfterId=null
    state.hasMore=false
    state.pageSize=null
    state.loadingMore=false
    state.loadMoreError=null
    state.error = null
    state.actionError = null
    state.reconciliationRequired = false
    state.reconciliationNotice = false
    state.busy = false
    state.status = "blocked"
  }
  function snapshot(signal: AbortSignal): QueryContext | null {
    const scope = projectContext.selection()
    return scope ? {
      scope,signal,revision:projectContext.state.revision,
      decisionVersion:verifiedDecisionVersion(scope),
    } : null
  }
  function readApplicable(context: QueryContext, generation: number): boolean {
    return !disposed && generation === readRun && !context.signal.aborted && sameScope(context.scope, context.revision)
  }
  function readCurrent(context: QueryContext, port: PlatformPort, generation: number): boolean {
    return readApplicable(context, generation) && port === platformPort.value
  }
  function canAcceptRead(context: QueryContext, port: PlatformPort, generation: number): boolean {
    if (!readCurrent(context, port, generation)) return false
    if (usable()) return true
    invalidate()
    return false
  }
  function writeApplicable(context: QueryContext, generation: number): boolean {
    return !disposed && generation === writeRun && !context.signal.aborted && sameScope(context.scope, context.revision)
  }
  function writeCurrent(context: QueryContext, port: PlatformPort, generation: number): boolean {
    return writeApplicable(context, generation) && port === platformPort.value
  }
  function ignoreWrite(pending: PendingCommand): false {
    commandCoordinator.uncertain(pending)
    if (activeWrite === pending) activeWrite = null
    return false
  }
  function readFailed(cause: unknown, context: QueryContext, generation: number, started: number, paging: boolean): void {
    if (!readApplicable(context, generation)) return
    const issue = normalizeUiError(cause)
    if (handlePermissionError(issue)) return
    if (paging) state.loadMoreError = issue
    else { state.error = issue; state.status = "error" }
    browserTelemetry.read(resource, diagnosticOutcome(issue), performance.now() - started)
  }
  function acceptSnapshot(result: DomainLoad<T>): void {
    state.items = result.items
    state.revision = result.revision ?? null
    state.serverLimit = result.serverLimit ?? null
    state.possiblyTruncated = result.possiblyTruncated === true
    state.observedAt = result.observedAt ?? null
    state.nextAfterId = result.nextAfterId ?? null
    state.hasMore = result.hasMore === true
    state.pageSize = result.pageSize ?? null
    state.status = result.items.length ? "ready" : "empty"
  }
  function acceptPage(result: DomainLoad<T>, cursor: string): void {
    if (!keyOf) throw new Error("Missing server row identity for keyset paging")
    if (state.revision && result.revision && state.revision !== result.revision) throw new Error("Source page revision changed")
    const verified = appendVerifiedKeyset(state.items, result, cursor, keyOf)
    state.items = verified.rows
    state.nextAfterId = verified.next
    state.hasMore = verified.hasMore
    state.possiblyTruncated = state.possiblyTruncated || result.possiblyTruncated === true
    state.pageSize = result.pageSize ?? state.pageSize
    state.status = state.items.length ? "ready" : "empty"
  }
  async function reload(): Promise<boolean> {
    ++readRun
    controller?.abort()
    pagination?.abort()
    pagination=null
    state.loadingMore=false
    state.loadMoreError=null
    state.nextAfterId=null
    state.hasMore=false
    state.pageSize=null
    controller = null
    state.error = null
    state.items = []
    state.revision = null
    state.serverLimit = null
    state.possiblyTruncated = false
    state.observedAt = null
    if (!usable() || disposed) { state.status = "blocked"; return false }
    const port = platformPort.value
    if (!port) { state.status = "blocked"; return false }
    const generation = readRun
    const telemetryStart=performance.now()
    const abort = new AbortController()
    controller = abort
    const context = snapshot(abort.signal)
    if (!context) { state.status = "blocked"; return false }
    state.status = "loading"
    try {
      const result = await read(port, context)
      if (!canAcceptRead(context, port, generation)) return false
      acceptSnapshot(result)
      browserTelemetry.read(resource,"ok",performance.now()-telemetryStart)
      return true
    } catch (cause) {
      readFailed(cause, context, generation, telemetryStart, false)
      return false
    } finally {
      if (controller === abort) controller = null
    }
  }
  function canLoadMore(): boolean {
    return !disposed && usable() && state.hasMore && Boolean(state.nextAfterId) &&
      !state.loadingMore && state.status !== "loading" && !state.busy
  }
  /** One bounded A6 keyset GET, never a background auto-fetch or fake snapshot. */
  async function loadMore():Promise<boolean> {
    if (!canLoadMore()) return false
    const port=platformPort.value
    if(!port)return false
    const cursor=state.nextAfterId
    if (!cursor) return false
    const version=readRun
    const telemetryStart=performance.now()
    const abort=new AbortController()
    pagination=abort
    const context=snapshot(abort.signal)
    if(!context)return false
    state.loadingMore=true
    state.loadMoreError=null
    try {
      const result=await read(port,context,cursor)
      if (!canAcceptRead(context, port, version)) return false
      acceptPage(result, cursor)
      browserTelemetry.read(resource,"ok",performance.now()-telemetryStart)
      return true
    } catch (error) {
      readFailed(error, context, version, telemetryStart, true)
      return false
    }finally{
      if(pagination===abort){pagination=null;state.loadingMore=false}
    }
  }
  function writable(action: UiCapability, port: PlatformPort | null): boolean {
    return usable() && projectContext.can(action) && !state.busy && !state.reconciliationRequired &&
      Boolean(port) && !disposed && !commandCoordinator.lookup(projectContext.state.user?.key ?? "", projectContext.selection())
  }
  function unconfirmedWrite(pending: PendingCommand, outcome: EffectOutcome, started: number): false {
    ignoreWrite(pending)
    if (outcome === "unconfirmed") {
      state.actionError = { kind: "uncertain", code: "bff_distributed_effect_unconfirmed", message: "crossOwnerOutcomeUnknown" }
      state.reconciliationRequired = true
      browserTelemetry.write(resource, "uncertain", performance.now() - started)
    }
    return false
  }
  function writeFailed(cause: unknown, context: QueryContext, generation: number, started: number): void {
    if (!writeApplicable(context, generation)) return
    const issue = normalizeUiError(cause, "mutation")
    if (handlePermissionError(issue)) return
    browserTelemetry.write(resource, diagnosticOutcome(issue), performance.now() - started)
    state.actionError = issue
    state.reconciliationRequired = true
  }
  function settleWrite(pending: PendingCommand, outcome: EffectOutcome, started: number): boolean {
    if (outcome !== "confirmed") return unconfirmedWrite(pending, outcome, started)
    commandCoordinator.confirm(pending)
    if (activeWrite === pending) activeWrite = null
    browserTelemetry.write(resource, "ok", performance.now() - started)
    return true
  }
  function releaseMutation(abort: AbortController): void {
    if (mutation === abort) { state.busy = false; mutation = null }
  }
  async function execute(action: UiCapability, write: WriteDomain, sourceOperation: string | SourceCommandBinding | null = null): Promise<boolean> {
    const port = platformPort.value
    if (!sourceMutationReady(action, sourceOperation)) { state.actionError = mutationBlockedIssue(sourceOperation); return false }
    if (!port || !writable(action, port)) return false
    const generation = ++writeRun
    const started = performance.now()
    const abort = new AbortController()
    mutation = abort
    const base = snapshot(abort.signal)
    if (!base) return false
    const principal = projectContext.state.user?.key ?? ""
    const pending = commandCoordinator.begin(principal, base.scope, action, base.decisionVersion ?? null, sourceOperation)
    if (!pending) return false
    activeWrite = pending
    const context: CommandContext = { ...base, idempotencyKey: pending.commandId, operationUuid: pending.operationUuid }
    state.busy = true
    state.actionError = null
    state.reconciliationNotice = false
    try {
      await write(port, context)
      const outcome = await verifyOriginalEffect({ port, context, entry: pending, principal,
        current: () => writeCurrent(base, port, generation), refresh: reload })
      return settleWrite(pending, outcome, started)
    } catch (cause) {
      ignoreWrite(pending)
      writeFailed(cause, base, generation, started)
      return false
    } finally {
      releaseMutation(abort)
    }
  }
  function reconciliationMatches(entry: PendingCommand | null, scope: ScopeSelection | null, principal: string): boolean {
    if (!entry) return true
    if (!scope) return false
    if (!commandCoordinator.matches(entry, principal, scope)) {
      state.actionError = { kind: "uncertain", code: "reconcile_scope_mismatch", message: "reconcileOriginalScope" }
      return false
    }
    if (resourceForAction(entry.action) !== resource) {
      state.actionError = { kind: "uncertain", code: "reconcile_domain_mismatch", message: "reconcileOriginalDomain" }
      return false
    }
    return true
  }
  function reconcileCurrent(context: QueryContext, port: PlatformPort, principal: string): boolean {
    return !disposed && !context.signal.aborted && sameScope(context.scope, context.revision) &&
      port === platformPort.value && principal === projectContext.state.user?.key
  }
  function reconciliationFailed(cause: unknown, context: QueryContext): void {
    if (disposed || context.signal.aborted || !sameScope(context.scope, context.revision)) return
    const issue = normalizeUiError(cause)
    if (!handlePermissionError(issue)) state.actionError = issue.kind === "unknown" ?
      { kind: "unavailable", code: "source_reconciliation_failed", message: "reconcileReadFailed" } : issue
  }
  async function refreshReconciledDomain(context: QueryContext, port: PlatformPort, principal: string): Promise<boolean> {
    if (!reconcileCurrent(context, port, principal) || !await reload()) return false
    return reconcileCurrent(context, port, principal)
  }
  function reconciliationOutcome(outcome: EffectOutcome): boolean {
    if (outcome === "unconfirmed") state.actionError = {
      kind: "uncertain", code: "bff_distributed_effect_unconfirmed", message: "crossOwnerOutcomeUnknown" }
    return outcome === "confirmed"
  }
  async function reconcileDomain(context: QueryContext, port: PlatformPort, principal: string, entry: PendingCommand | null): Promise<boolean> {
    if (!entry) return refreshReconciledDomain(context, port, principal)
    const outcome = await verifyOriginalEffect({ port, context, entry, principal,
      current: () => reconcileCurrent(context, port, principal), refresh: reload })
    if (!reconciliationOutcome(outcome)) return false
    if (commandCoordinator.reconcile(principal, context.scope, entry, resource as CommandResource)) return true
    state.actionError = { kind: "uncertain", code: "reconcile_scope_mismatch", message: "reconcileOriginalScope" }
    return false
  }
  /** Verify A5 outcome (when Project-owned), THEN read authoritative effect domain. */
  async function reconcile():Promise<boolean> {
    if(state.busy||disposed)return false
    const scope=projectContext.selection()
    const principal=projectContext.state.user?.key??""
    const port=platformPort.value
    const entry=commandCoordinator.lookup(principal,scope)
    if (!reconciliationMatches(entry, scope, principal)) return false
    if(!scope||!port)return false
    const revision=projectContext.state.revision
    const lifetime = openReconciliation(entry)
    try {
      const context:QueryContext={scope,signal:lifetime.signal,revision,decisionVersion:verifiedDecisionVersion(scope)}
      if (!await reconcileDomain(context, port, principal, entry)) return false
      state.reconciliationRequired=false
      state.actionError=null
      state.reconciliationNotice=Boolean(entry)
      return true
    } catch (cause) {
      reconciliationFailed(cause, { scope, revision, signal: lifetime.signal })
      return false
    }finally{
      lifetime.close()
    }
  }

  const stop = watch(() => [projectContext.state.revision, platformPort.value] as const, () => {
    invalidate()
    if (usable()) void reload()
  }, { immediate: true })
  const unsubscribe = scopedEvents.subscribe(event => {
    if (event.resource === resource || event.resource === "all") void reload()
  })
  onBeforeUnmount(() => { disposed = true; stop(); unsubscribe(); invalidate() })
  return { state, reload, loadMore, execute, reconcile, usable }
}

/** Standalone mutation needs a verified list-read to unlock uncertain results. */
export function useCommand(scopes: ScopeSelection["kind"][] = ["account", "team", "project", "operator"]) {
  const state = reactive({ busy: false, error: null as UiError | null, reconciliationRequired: false, reconciliationNotice: false })
  let active: AbortController | null = null
  let nonce = 0
  let disposed = false
  const currentEntry = computed(() => commandCoordinator.lookup(
    projectContext.state.user?.key ?? "", projectContext.selection(),
  ))
  const stopBarrier = watchEffect(() => {
    const blocked = currentEntry.value !== null
    const unconfirmed = ["unknown","reconciling"].includes(currentEntry.value?.state??"")
    state.reconciliationRequired = blocked
    if (unconfirmed && !state.error) {
      state.error = { kind: "uncertain", code: "command_outcome_pending", message: "outcomeUncertain" }
    }
    if (!blocked && state.error?.code === "command_outcome_pending") state.error = null
  })
  let commandInFlight: PendingCommand | null = null
  function invalidate(): void {
    ++nonce
    if (commandInFlight) commandCoordinator.uncertain(commandInFlight)
    commandInFlight = null
    active?.abort()
    active = null
    state.busy = false
    state.error = null
    state.reconciliationRequired = false
    state.reconciliationNotice = false
  }
  const stop = projectContext.onTransition(invalidate)
  const stopAdapter = watch(platformPort, invalidate)
  function commandCurrent(scope: ScopeSelection, revision: number, port: PlatformPort,
    signal: AbortSignal, generation = nonce): boolean {
    return !disposed && !signal.aborted && nonce === generation && sameScope(scope, revision) && platformPort.value === port
  }
  function commandAllowed(scope: ScopeSelection | null, port: PlatformPort, ability: UiCapability): boolean {
    return !disposed && !state.busy && !state.reconciliationRequired && Boolean(groupVerifiedBffCapabilities(port)) &&
      Boolean(scope && scopes.includes(scope.kind)) && projectContext.can(ability)
  }
  function uncertainCommand(pending: PendingCommand): void {
    commandCoordinator.uncertain(pending)
    if (commandInFlight === pending) commandInFlight = null
  }
  function unconfirmedCommand(pending: PendingCommand, outcome: EffectOutcome, resource: string, started: number): false {
    uncertainCommand(pending)
    if (outcome === "unconfirmed") {
      state.error = { kind: "uncertain", code: "bff_distributed_effect_unconfirmed", message: "crossOwnerOutcomeUnknown" }
      state.reconciliationRequired = true
      browserTelemetry.write(resource, "uncertain", performance.now() - started)
    }
    return false
  }
  function commandFailed(cause: unknown, resource: string, started: number): void {
    const issue = normalizeUiError(cause, "mutation")
    if (handlePermissionError(issue)) return
    browserTelemetry.write(resource, diagnosticOutcome(issue), performance.now() - started)
    state.error = issue
    state.reconciliationRequired = true
  }
  function settleCommand(pending: PendingCommand, outcome: EffectOutcome, resource: string, started: number): boolean {
    if (outcome !== "confirmed") return unconfirmedCommand(pending, outcome, resource, started)
    commandCoordinator.confirm(pending)
    commandInFlight = null
    browserTelemetry.write(resource, "ok", performance.now() - started)
    return true
  }
  function releaseCommand(abort: AbortController): void {
    if (active === abort) { state.busy = false; active = null }
  }
  async function submit(ability: UiCapability, action: WriteDomain, sourceOperation: string | SourceCommandBinding | null = null): Promise<boolean> {
    const port = platformPort.value
    if (!sourceMutationReady(ability, sourceOperation)) { state.error = mutationBlockedIssue(sourceOperation); return false }
    const scope = projectContext.selection()
    if (!port || !scope || !commandAllowed(scope, port, ability)) return false
    const actor = projectContext.state.user?.key ?? ""
    const generation = ++nonce
    const started = performance.now()
    const resource = resourceForAction(ability) ?? "other"
    const abort = new AbortController()
    const revision = projectContext.state.revision
    const pending = commandCoordinator.begin(actor, scope, ability, verifiedDecisionVersion(scope), sourceOperation)
    if (!pending) return false
    active = abort
    commandInFlight = pending
    state.busy = true
    state.error = null
    state.reconciliationNotice = false
    const context: CommandContext = { scope, revision, signal: abort.signal,
      idempotencyKey: pending.commandId, operationUuid: pending.operationUuid, decisionVersion: pending.decisionVersion }
    const current = () => commandCurrent(scope, revision, port, abort.signal, generation)
    try {
      await action(port, context)
      const outcome = await verifyOriginalEffect({ port, context, entry: pending, principal: actor, current })
      return settleCommand(pending, outcome, resource, started)
    } catch (cause) {
      uncertainCommand(pending)
      if (current()) commandFailed(cause, resource, started)
      return false
    } finally {
      releaseCommand(abort)
    }
  }
  function originalCommandMatches(entry: PendingCommand, principal: string, scope: ScopeSelection): boolean {
    if (commandCoordinator.matches(entry, principal, scope)) return true
    state.error = { kind: "uncertain", code: "reconcile_scope_mismatch", message: "reconcileOriginalScope" }
    return false
  }
  function reconcileFailed(cause: unknown, scope: ScopeSelection, revision: number, signal: AbortSignal): void {
    if (disposed || signal.aborted || !sameScope(scope, revision)) return
    const issue = normalizeUiError(cause)
    state.error = issue.kind === "unknown" ?
      { kind: "unavailable", code: "source_reconciliation_failed", message: "reconcileReadFailed" } : issue
    if (issue.kind === "unauthorized" || issue.kind === "forbidden") handlePermissionError(issue)
  }
  function settleReconciliation(entry: PendingCommand, principal: string, scope: ScopeSelection,
    resource: CommandResource, outcome: EffectOutcome): boolean {
    if (outcome === "unconfirmed") state.error = {
      kind: "uncertain", code: "bff_distributed_effect_unconfirmed", message: "crossOwnerOutcomeUnknown" }
    if (outcome !== "confirmed") return false
    if (!originalCommandMatches(entry, principal, scope)) return false
    if (!commandCoordinator.reconcile(principal, scope, entry, resource)) {
      state.error = { kind: "uncertain", code: "reconcile_scope_mismatch", message: "reconcileOriginalScope" }
      return false
    }
    state.error = null
    state.reconciliationRequired = false
    state.reconciliationNotice = true
    return true
  }
  async function reconcile(): Promise<boolean> {
    if (disposed || state.busy) return false
    const scope = projectContext.selection()
    const revision = projectContext.state.revision
    const port = platformPort.value
    const principal = projectContext.state.user?.key ?? ""
    const entry = commandCoordinator.lookup(principal, scope)
    if (!scope || !port || !entry) return false
    if (!originalCommandMatches(entry, principal, scope)) return false
    const resource = resourceForAction(entry.action)
    if (!resource) { state.error = { kind: "unavailable", code: "command_status_required", message: "serverCommandStatusRequired" }; return false }
    const lifetime = openReconciliation(entry)
    try {
      const context: QueryContext = { scope, signal: lifetime.signal, revision, decisionVersion: verifiedDecisionVersion(scope) }
      const current = () => commandCurrent(scope, revision, port, lifetime.signal) && principal === projectContext.state.user?.key
      const outcome = await verifyOriginalEffect({ port, context, entry, principal, current })
      return settleReconciliation(entry, principal, scope, resource, outcome)
    } catch (cause) {
      reconcileFailed(cause, scope, revision, lifetime.signal)
      return false
    } finally {
      lifetime.close()
    }
  }
  onBeforeUnmount(() => { disposed = true; stop(); stopAdapter(); stopBarrier(); invalidate() })
  return { state, submit, reconcile }
}
