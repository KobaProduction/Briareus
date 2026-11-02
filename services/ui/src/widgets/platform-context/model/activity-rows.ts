import type { CurrentAgentSession } from "@/entities/agent-session";
import type { ApprovalAction, ApprovalRecord } from "@/entities/approval";
import { presentPermissions, shortIdentifier } from "@/entities/permission";
import type { ActivityRow } from "@/shared/ui/data-table";

interface ActivityReadContext {
  actorId?: string;
  actorNames?: Record<string, string>;
  locale: string;
  pending: boolean;
  canInspect: () => boolean;
  inspect: (id: string) => void;
}
export interface SessionActivityContext extends ActivityReadContext {
  labels: Record<CurrentAgentSession["status"] | "inspect" | "revoke", string>;
  canRevoke: (item: CurrentAgentSession) => boolean;
  requestRevoke: (item: CurrentAgentSession) => void;
}
export interface ApprovalActivityContext extends ActivityReadContext {
  projectId: string;
  labels: Record<
    ApprovalRecord["status"] | "inspectRequest" | "inspectIssued" | ApprovalAction,
    string
  >;
  canDecide: (item: ApprovalRecord, action: ApprovalAction) => boolean;
  requestDecision: (item: ApprovalRecord, action: ApprovalAction) => void;
  inspectIssued: (id: string) => void;
}
function actorName(id: string, context: ActivityReadContext): string {
  return context.actorNames?.[id] || (id === context.actorId ? "Вы" : "Пользователь");
}
function guardedInspect(id: string, context: ActivityReadContext): () => void {
  return () => {
    if (context.canInspect()) context.inspect(id);
  };
}
function sessionActions(
  item: CurrentAgentSession,
  context: SessionActivityContext,
): ActivityRow["actions"] {
  const actions: ActivityRow["actions"] = [
    {
      label: context.labels.inspect,
      disabled: context.pending,
      run: guardedInspect(item.session_uuid, context),
    },
  ];
  if (context.canRevoke(item))
    actions.push({ label: context.labels.revoke, run: () => context.requestRevoke(item) });
  return actions;
}
export function sessionActivityRow(
  item: CurrentAgentSession,
  context: SessionActivityContext,
): ActivityRow {
  return {
    id: item.session_uuid,
    projectId: item.project_uuid,
    name: shortIdentifier(item.session_uuid),
    sessionId: item.session_uuid,
    description: item.label,
    created: item.created_at,
    statusCode: item.status,
    expiresAt: item.hard_expires_at,
    permissions: presentPermissions(item.operations, item.resources),
    inspect: guardedInspect(item.session_uuid, context),
    actor: actorName(item.created_by_user_uuid, context),
    operations: item.operations.join(", "),
    status: context.labels[item.status],
    expires: new Date(item.hard_expires_at).toLocaleString(context.locale),
    actions: sessionActions(item, context),
  };
}
function approvalActions(
  item: ApprovalRecord,
  context: ApprovalActivityContext,
): ActivityRow["actions"] {
  const actions: ActivityRow["actions"] = [
    {
      label: context.labels.inspectRequest,
      disabled: context.pending,
      run: guardedInspect(item.id, context),
    },
  ];
  for (const action of ["approve", "deny"] as const)
    if (context.canDecide(item, action))
      actions.push({
        label: context.labels[action],
        run: () => context.requestDecision(item, action),
      });
  const issued = item.status === "approved" ? item.issued_session_uuid : null;
  if (issued)
    actions.push({
      label: context.labels.inspectIssued,
      disabled: context.pending,
      run: () => {
        if (context.canInspect()) context.inspectIssued(issued);
      },
    });
  return actions;
}
export function approvalActivityRow(
  item: ApprovalRecord,
  context: ApprovalActivityContext,
): ActivityRow {
  return {
    id: item.id,
    projectId: context.projectId,
    name: shortIdentifier(item.id),
    description: item.label,
    created: item.created_at,
    sessionId: item.agent_session_uuid,
    statusCode: item.status,
    expiresAt: item.requested_expires_at,
    permissions: presentPermissions(item.requested_operations, item.requested_resources),
    inspect: guardedInspect(item.id, context),
    actor: actorName(item.requested_by_user_uuid, context),
    operations: item.requested_operations.join(", "),
    status: context.labels[item.status],
    expires: new Date(item.requested_expires_at).toLocaleString(context.locale),
    actions: approvalActions(item, context),
  };
}
