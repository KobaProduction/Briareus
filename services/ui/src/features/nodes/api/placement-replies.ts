import type { Placement } from "../model/placement-intent";
import type { FailureDiagnostic, PlacementOperation } from "../model/operation-presentation";
import type { ProjectWorkspace, ProjectWorkspaceMount } from "../model/project-workspace";
import { decodeModuleConfiguration } from "./configuration-replies";
import {
  replyArray,
  replyBoolean,
  replyChoice,
  replyInstant,
  replyLimits,
  replyNumber,
  replyRecord,
  replyString,
  replyUuid,
} from "./node-reply-values";
const diagnosticReasons = [
  "process_exited",
  "oom",
  "readiness_timeout",
  "unhealthy",
  "helper_unhealthy",
  "pull_failed",
  "unknown",
  "workspace_cleanup_uncertain",
  "workspace_initialization_failed",
  "workspace_identity_unverified",
  "network_policy_cleanup_uncertain",
  "network_policy_failed",
  "network_policy_unverified",
  "engine_unavailable",
  "engine_request_rejected",
  "rootless_unverified",
  "network_address_conflict",
] as const;
function diagnostic(value: unknown): FailureDiagnostic | null {
  if (value === null || value === undefined) return null;
  const item = replyRecord(value);
  const result: FailureDiagnostic = {
    stage: replyChoice(item.stage, [
      "queued",
      "pulling",
      "stopping",
      "creating",
      "checking",
      "rolling_back",
      "unknown",
    ]),
    component: replyChoice(item.component, ["worker", "egress", "engine", "controller"]),
    reason: replyChoice(item.reason, diagnosticReasons),
  };
  if (item.exit_code !== undefined && item.exit_code !== null)
    result.exit_code = replyNumber(item.exit_code, 0, 255);
  if (item.health_exit_code !== undefined && item.health_exit_code !== null)
    result.health_exit_code = replyNumber(item.health_exit_code, -1, 255);
  if (item.health_status !== undefined && item.health_status !== null)
    result.health_status = replyChoice(item.health_status, [
      "starting",
      "healthy",
      "unhealthy",
      "none",
    ]);
  if (item.oom_killed !== undefined && item.oom_killed !== null)
    result.oom_killed = replyBoolean(item.oom_killed);
  return result;
}
function operation(value: unknown): PlacementOperation | null {
  if (value === null) return null;
  const item = replyRecord(value);
  return {
    id: replyUuid(item.id),
    phase: replyString(item.phase, 64),
    error: item.error === null ? null : replyString(item.error, 128),
    reconciliation_required: replyBoolean(item.reconciliation_required),
    restored: replyBoolean(item.restored),
    updated_at: replyInstant(item.updated_at),
    diagnostic: diagnostic(item.diagnostic),
  };
}
function workspaceMount(value: unknown): ProjectWorkspaceMount | null {
  if (value === null || value === undefined) return null;
  const mount = replyRecord(value);
  return { id: replyUuid(mount.id), read_only: replyBoolean(mount.read_only) };
}
interface PlacementScope {
  projectId: string;
  nodeId?: string;
}
function placement(value: unknown, scope: PlacementScope): Placement {
  const item = replyRecord(value),
    project = replyUuid(item.project_uuid),
    node = replyUuid(item.node_uuid);
  if (project !== scope.projectId || (scope.nodeId !== undefined && node !== scope.nodeId))
    throw Error("NODE_RESPONSE_SCOPE_INVALID");
  return {
    id: replyUuid(item.id),
    name: replyString(item.name, 128),
    module: replyString(item.module, 128),
    state: replyString(item.state, 64),
    sequence: replyNumber(item.sequence, 1),
    runtime_policy_pending: replyBoolean(item.runtime_policy_pending),
    release_uuid: replyUuid(item.release_uuid),
    limits: replyLimits(item.limits),
    workspace_uuid: item.workspace_uuid === null ? null : replyUuid(item.workspace_uuid),
    configuration: decodeModuleConfiguration(item.configuration),
    project_workspace: workspaceMount(item.project_workspace),
    operation: operation(item.operation),
  };
}
export function decodePlacements(value: unknown, scope: PlacementScope): { items: Placement[] } {
  return { items: replyArray(replyRecord(value).items, (item) => placement(item, scope)) };
}
function workspace(value: unknown, projectId: string, nodeId: string): ProjectWorkspace {
  const item = replyRecord(value);
  const result: ProjectWorkspace = {
    id: replyUuid(item.id),
    project_uuid: replyUuid(item.project_uuid),
    node_uuid: replyUuid(item.node_uuid),
    purpose: replyChoice(item.purpose, ["workspace"]),
    retention: replyChoice(item.retention, ["persistent"]),
  };
  if (result.project_uuid !== projectId || result.node_uuid !== nodeId)
    throw Error("NODE_RESPONSE_SCOPE_INVALID");
  return result;
}
export function decodeWorkspaces(
  value: unknown,
  projectId: string,
  nodeId: string,
): { items: ProjectWorkspace[] } {
  return {
    items: replyArray(replyRecord(value).items, (item) => workspace(item, projectId, nodeId), 1),
  };
}
export function decodeEnsuredWorkspace(
  value: unknown,
  projectId: string,
  nodeId: string,
): { item: ProjectWorkspace } {
  return { item: workspace(replyRecord(value).item, projectId, nodeId) };
}
