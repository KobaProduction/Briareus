import { confirmedBffEffect, crossOwnerMutation } from "./bff-evidence";
import {
  type CommandResource,
  type PendingCommand,
  resourceForAction,
} from "./command-coordinator";
import { canonicalUuid4, type ListResult, type PlatformPort, type QueryContext } from "./contracts";
import { projectContext } from "./project-context";
import { refreshBffOwnerBoundary } from "./refresh-owner-boundary";
import { sameScope } from "./scope-lifetime";

type EffectRead = (port: PlatformPort, context: QueryContext, principal: string) => Promise<void>;
function requireItems<T>(snapshot: ListResult<T>, resource: string): void {
  if (!Array.isArray(snapshot.items))
    throw new Error(`Authoritative ${resource} snapshot unavailable`);
}
function requireScope(context: QueryContext, kinds: QueryContext["scope"]["kind"][]): void {
  if (!kinds.includes(context.scope.kind)) throw new Error("Original effect owner scope required");
}
const effectReads: Record<CommandResource, EffectRead> = {
  profile: async (port, context, principal) => {
    const projection = await port.auth.refresh(context.signal);
    if (!projection?.user.active || projection.user.userId !== principal)
      throw new Error("Authoritative principal read unavailable");
  },
  invitations: async (port, context) =>
    requireItems(await port.users.invitations(context), "invitations"),
  users: async (port, context) => {
    requireScope(context, ["operator"]);
    requireItems(await port.users.list(context), "Users");
  },
  teams: async (port, context) => requireItems(await port.teams.list(context), "Teams"),
  projects: async (port, context) => requireItems(await port.projects.list(context), "Projects"),
  agents: async (port, context) => {
    requireScope(context, ["project"]);
    requireItems(await port.agents.list(context), "Agents");
  },
  sessions: async (port, context) => {
    requireScope(context, ["project"]);
    const snapshot = await port.sessions.list(context);
    if (!Array.isArray(snapshot.sessions) || !Array.isArray(snapshot.requests))
      throw new Error("Authoritative Session snapshot unavailable");
  },
  accounts: async (port, context) => {
    requireScope(context, ["project", "team"]);
    requireItems(await port.accounts.list(context, { scope: "all" }), "connection");
  },
  variables: async (port, context) => {
    requireScope(context, ["project", "team"]);
    requireItems(await port.variables.list(context, { scope: "all" }), "Variable");
  },
};
/** A typed read of the ORIGINAL effect domain, never an unrelated successful GET. */
export async function readActionDomain(
  port: PlatformPort,
  context: QueryContext,
  resource: CommandResource,
  principal: string,
): Promise<void> {
  await effectReads[resource](port, context, principal);
}
/** A single bounded GET of the immutable original, never a retry POST. */
export async function completeCrossOwnerEffect(
  port: PlatformPort,
  context: QueryContext,
  entry: PendingCommand,
): Promise<boolean> {
  if (!crossOwnerMutation(entry.action)) return true;
  if (!canonicalUuid4(entry.commandId) || entry.operationUuid !== entry.commandId) return false;
  if (!port.bff?.inspectOriginalCommand || !entry.sourceOperation || !entry.sourceTarget)
    return false;
  const binding = { operation: entry.sourceOperation, target: entry.sourceTarget };
  if (
    !(await refreshBffOwnerBoundary()) ||
    context.signal.aborted ||
    !sameScope(context.scope, context.revision)
  )
    return false;
  const evidence = projectContext.state.ownerEvidence;
  if (!evidence) return false;
  const signal = AbortSignal.any([context.signal, AbortSignal.timeout(5_000)]);
  const result = await port.bff.inspectOriginalCommand(
    { ...context, signal },
    {
      binding,
      idempotencyKey: entry.commandId,
      operationUuid: entry.operationUuid,
    },
  );
  if (signal.aborted) return false;
  return confirmedBffEffect(result, {
    actor: projectContext.state.user?.key ?? "",
    scope: context.scope,
    binding,
    idempotencyKey: entry.commandId,
    operationUuid: entry.operationUuid,
    action: entry.action,
    ownerEvidence: evidence,
  });
}
export type EffectOutcome = "confirmed" | "unconfirmed" | "stale";
export interface EffectVerification {
  port: PlatformPort;
  context: QueryContext;
  entry: PendingCommand;
  principal: string;
  current: () => boolean;
  refresh?: () => Promise<boolean>;
}
/** Preserve ordering: current epoch -> all owner ACKs -> affected read -> UI refresh.
 * Each await rechecks the caller's own read/write generation before proceeding. */
export async function verifyOriginalEffect(request: EffectVerification): Promise<EffectOutcome> {
  const { port, context, entry, principal, current, refresh } = request;
  if (!current()) return "stale";
  if (!(await completeCrossOwnerEffect(port, context, entry))) return "unconfirmed";
  if (!current()) return "stale";
  const affected = resourceForAction(entry.action);
  if (!affected) throw new Error("Missing original effect domain");
  await readActionDomain(port, context, affected, principal);
  if (!current()) return "stale";
  if (refresh && !(await refresh())) return "stale";
  return current() ? "confirmed" : "stale";
}
